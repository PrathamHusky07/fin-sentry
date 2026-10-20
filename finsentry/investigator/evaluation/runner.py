"""
Run an investigator over the known-answer suite and record the result so another version can
be compared against it later.

The record names the agent version, the tool contract version, the harness version, a
fingerprint of every case and a version of the scoring rules, then lists each case's score
and any failure. The suite fingerprint covers cases and scoring together, so a score that moved
because the rubric changed can be told from one that moved because the agent did. The record
holds no timestamp or machine detail, so the same investigator on the same suite writes the
same file.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import InvestigationResult, InvestigationState
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.scorer import (
    PASS_THRESHOLD,
    CaseScore,
    score_case,
    scoring_version,
)
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import (
    Clock,
    InvestigationFailedError,
    Investigator,
    start_investigation,
)
from finsentry.investigator.tool_contract import TOOL_CONTRACT_VERSION

HARNESS_VERSION = "known-answer-2"


@dataclass(frozen=True)
class SuiteResult:
    agent_version: str
    tool_contract_version: str
    harness_version: str
    cases_fingerprint: str
    scoring_version: str
    suite_fingerprint: str
    pass_threshold: float
    cases: list[CaseScore]
    summary: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def _failure(
    case: IncidentCase, error: str, adapter: ReadOnlyAdapter, state: InvestigationState | None
) -> CaseScore:
    """A failed case keeps what it spent: the tool calls the adapter saw and, when the failure
    carried its state, the inference calls and the tool calls that state recorded."""
    score = score_case(case, None, None, error)
    tool_calls = max(adapter.calls_made, state.usage.tool_calls if state else 0)
    inference_calls = state.usage.inference_calls if state else 0
    return replace(score, tool_calls=tool_calls, inference_calls=inference_calls)


async def run_case(
    investigator: Investigator, case: IncidentCase, clock: Clock = time.monotonic
) -> CaseScore:
    """Run one case in a fresh world. An investigator that raises, or returns something that
    is not a result, is scored as a failure with its error and spend kept. It never aborts the
    suite."""
    world = FixtureWorld(case.world)
    adapter = ReadOnlyAdapter(world)
    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    try:
        result: InvestigationResult = await investigator.investigate(state, adapter, clock)
    except Exception as exc:
        carried = exc.state if isinstance(exc, InvestigationFailedError) else None
        return _failure(case, f"{type(exc).__name__}: {exc}", adapter, carried)
    try:
        return score_case(case, result, validate_report(result.report, result.state))
    except Exception as exc:
        return _failure(case, f"malformed result: {type(exc).__name__}: {exc}", adapter, None)


def _summary(scores: list[CaseScore]) -> dict[str, object]:
    by_outcome: dict[str, dict[str, int]] = {}
    for s in scores:
        row = by_outcome.setdefault(s.expected_outcome, {"cases": 0, "passed": 0})
        row["cases"] += 1
        row["passed"] += s.passed
    return {
        "cases": len(scores),
        "passed": sum(s.passed for s in scores),
        "failed": [s.case_id for s in scores if not s.passed],
        "mean_score": round(sum(s.total for s in scores) / len(scores), 4),
        "by_expected_outcome": by_outcome,
        "safety_passed": sum(s.safety_pass for s in scores),
        "diagnostic": {
            d: sum(1 for s in scores if s.diagnostic == d)
            for d in ("pass", "incomplete", "fail", "not_applicable")
        },
        "tool_calls_total": sum(s.tool_calls for s in scores),
        "inference_calls_total": sum(s.inference_calls for s in scores),
    }


async def run_suite(
    investigator: Investigator,
    cases: list[IncidentCase] | None = None,
    clock: Clock = time.monotonic,
) -> SuiteResult:
    suite = cases if cases is not None else all_cases()
    scores = [await run_case(investigator, case, clock) for case in suite]
    cases_fingerprint = hashlib.sha256(
        "".join(c.fingerprint() for c in suite).encode()
    ).hexdigest()[:16]
    rules = scoring_version()
    suite_fingerprint = hashlib.sha256(f"{cases_fingerprint}{rules}".encode()).hexdigest()[:16]
    return SuiteResult(
        agent_version=investigator.agent_version,
        tool_contract_version=TOOL_CONTRACT_VERSION,
        harness_version=HARNESS_VERSION,
        cases_fingerprint=cases_fingerprint,
        scoring_version=rules,
        suite_fingerprint=suite_fingerprint,
        pass_threshold=PASS_THRESHOLD,
        cases=scores,
        summary=_summary(scores),
    )


def write_result(result: SuiteResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.to_json())
