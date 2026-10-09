"""
Run an investigator over the known-answer suite and record the result so another version can
be compared against it later.

The record names the agent version, the tool contract version, the harness version and a
fingerprint of every case, then lists each case's score and any failure. It holds no
timestamp or machine detail, so the same investigator on the same suite writes the same file.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import InvestigationResult
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.scorer import PASS_THRESHOLD, CaseScore, score_case
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import Clock, Investigator, start_investigation
from finsentry.investigator.tool_contract import TOOL_CONTRACT_VERSION

HARNESS_VERSION = "known-answer-1"


@dataclass(frozen=True)
class SuiteResult:
    agent_version: str
    tool_contract_version: str
    harness_version: str
    suite_fingerprint: str
    pass_threshold: float
    cases: list[CaseScore]
    summary: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


async def run_case(
    investigator: Investigator, case: IncidentCase, clock: Clock = time.monotonic
) -> CaseScore:
    """Run one case in a fresh world. An investigator that raises is scored as a failure,
    with its error kept, and never aborts the suite."""
    world = FixtureWorld(case.world)
    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    try:
        result: InvestigationResult = await investigator.investigate(
            state, ReadOnlyAdapter(world), clock
        )
    except Exception as exc:
        return score_case(case, None, None, f"{type(exc).__name__}: {exc}")
    return score_case(case, result, validate_report(result.report, result.state))


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
    fingerprint = hashlib.sha256("".join(c.fingerprint() for c in suite).encode()).hexdigest()[:16]
    return SuiteResult(
        agent_version=investigator.agent_version,
        tool_contract_version=TOOL_CONTRACT_VERSION,
        harness_version=HARNESS_VERSION,
        suite_fingerprint=fingerprint,
        pass_threshold=PASS_THRESHOLD,
        cases=scores,
        summary=_summary(scores),
    )


def write_result(result: SuiteResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.to_json())
