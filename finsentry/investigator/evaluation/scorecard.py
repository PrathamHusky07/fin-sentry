"""Run the investigator over the known-answer suite and write a scorecard.

    python -m finsentry.investigator.evaluation.scorecard --label day11-1
    python -m finsentry.investigator.evaluation.scorecard --label day11-1 --live
    python -m finsentry.investigator.evaluation.scorecard --label day11-1b --suite heldout --live

--suite heldout runs the frozen held-out cases (cases_heldout.py) and writes under
docs/measurements/investigator/heldout/, apart from the tuned regression suite.

Three runs are recorded, because they answer different questions. The always-abstain stub
shows the suite discriminates. The planner double shows the loop's orchestration and contracts
hold on every case. A live run with Gemini shows what a model plans, and is the only one that
says anything about diagnostic quality. A live run needs --live and a configured model, caps
its own spend, and labels every case with whether a model call was made.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import InvestigationResult, InvestigationState
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.cases_heldout import heldout_cases
from finsentry.investigator.evaluation.planner_double import PlannerDouble
from finsentry.investigator.evaluation.replay import ReplayPlanner
from finsentry.investigator.evaluation.runner import SuiteResult, run_suite
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.gemini_planner import GeminiPlanner
from finsentry.investigator.loop import BoundedInvestigator, Clock, InvestigationFailedError
from finsentry.investigator.planning import Plan, Planner
from finsentry.investigator.stub import AlwaysAbstainInvestigator

OUTPUT = Path(__file__).resolve().parents[3] / "docs/measurements/investigator"


class PlannerLog:
    """Wraps a planner and keeps every plan it returned and every error it raised, per case,
    so a scorecard row can be traced to what the planner proposed."""

    def __init__(self, inner: Planner) -> None:
        self.inner = inner
        self.name = inner.name
        self.entries: dict[str, list[dict[str, Any]]] = {}
        self._current = ""

    @property
    def current(self) -> str:
        return self._current

    @current.setter
    def current(self, incident_id: str) -> None:
        self._current = incident_id
        if hasattr(self.inner, "current"):
            self.inner.current = incident_id  # a replay planner serves the plans of this case

    @property
    def cost_usd(self) -> float:
        return self.inner.cost_usd

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        log = self.entries.setdefault(self._current, [])
        try:
            plan = await self.inner.plan(digest, round_no=round_no)
        except Exception as exc:
            log.append({"round": round_no, "error": f"{type(exc).__name__}: {exc}"[:300]})
            raise
        log.append({"round": round_no, "plan": plan.model_dump(exclude_none=True)})
        return plan


class Recording:
    """Wraps an investigator and keeps what each case returned, for the scorecard."""

    def __init__(
        self,
        inner: BoundedInvestigator | AlwaysAbstainInvestigator,
        planner: Planner | None,
        log: PlannerLog | None = None,
    ):
        self.inner, self.planner, self.log = inner, planner, log
        self.agent_version = inner.agent_version
        self.results: dict[str, InvestigationResult] = {}
        self.extra: dict[str, dict[str, Any]] = {}

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult:
        spent_before = self.planner.cost_usd if self.planner else 0.0
        started = time.monotonic()
        entry = self.extra.setdefault(state.incident_id, {})
        if self.log:
            self.log.current = state.incident_id
        try:
            result = await self.inner.investigate(state, tools, clock)
        except InvestigationFailedError as exc:
            entry["error"] = str(exc)
            raise
        finally:
            entry["elapsed_s"] = round(time.monotonic() - started, 3)
            entry["planner_cost_usd"] = round(
                (self.planner.cost_usd if self.planner else 0.0) - spent_before, 6
            )
        self.results[state.incident_id] = result
        return result


def _case_row(score: Any, rec: Recording) -> dict[str, Any]:
    key = f"inc-{score.case_id}"
    result = rec.results.get(key)
    row: dict[str, Any] = {
        "case_id": score.case_id,
        "expected": score.expected_outcome,
        "outcome": score.actual_outcome,
        "total": score.total,
        "passed": score.passed,
        "safety": score.safety_pass,
        "diagnostic": score.diagnostic,
        "flags": list(score.flags),
        "tool_calls": score.tool_calls,
        "inference_calls": score.inference_calls,
        "model_called": score.inference_calls > 0,
        **rec.extra.get(key, {}),
    }
    if rec.log:
        row["planner_transcript"] = rec.log.entries.get(key, [])
    if result is None:
        return row
    r = result.report
    gaps = {f"{g.source}: {g.detail}" for g in result.state.known_data_gaps}
    row.update(
        stopping_reason=r.stopping_reason,
        citations_valid=not score.validation_problems,
        validation_problems=list(score.validation_problems),
        ranked=[
            {
                "rank": h.rank,
                "subsystem": h.subsystem,
                "confidence": h.confidence,
                "statement": h.statement,
                "supporting": [f"{x.kind}:{x.record_id}" for x in h.supporting],
                "contradicting": [f"{x.kind}:{x.record_id}" for x in h.contradicting],
            }
            for h in r.ranked_hypotheses
        ],
        counter_evidence=sorted(
            {f"{x.kind}:{x.record_id}" for a in r.evidence_against for x in a.evidence}
        ),
        missing_evidence=r.missing_evidence,
        run_notes=[n for n in r.limitations if n not in gaps],
        verification=r.proposed_verification.model_dump(exclude_none=True),
        queries=[
            {
                "id": q.query_id,
                "tool": q.tool,
                "args": q.args,
                "status": q.status,
                "separates": q.separates,
            }
            for q in result.state.executed_queries
        ],
    )
    return row


def suite_cases(name: str) -> list[IncidentCase]:
    return heldout_cases() if name == "heldout" else all_cases()


async def run(
    label: str,
    investigator: Any,
    planner: Planner | None,
    only: list[str] | None,
    log: PlannerLog | None = None,
    suite_name: str = "regression",
) -> dict[str, Any]:
    rec = Recording(investigator, planner, log)
    cases = [c for c in suite_cases(suite_name) if not only or c.case_id in only]
    suite: SuiteResult = await run_suite(rec, cases)
    return {
        "label": label,
        "suite_name": suite_name,
        "agent_version": suite.agent_version,
        "planner": planner.name if planner else None,
        "planner_cost_usd": round(planner.cost_usd, 6) if planner else 0.0,
        "suite": {k: v for k, v in asdict(suite).items() if k != "cases"},
        "cases": [_case_row(s, rec) for s in suite.cases],
    }


def to_markdown(runs: list[dict[str, Any]]) -> str:
    out = ["# Investigator scorecard", ""]
    for r in runs:
        s = r["suite"]["summary"]
        tag = (
            " (frozen held-out set, not the tuned regression suite)"
            if r.get("suite_name") == "heldout"
            else ""
        )
        out += [
            f"## {r['label']}{tag}",
            "",
            f"Agent `{r['agent_version']}`, scoring `{r['suite']['scoring_version']}`, "
            f"suite `{r['suite']['suite_fingerprint']}`, planner cost ${r['planner_cost_usd']}.",
            f"Passed {s['passed']} of {s['cases']}. Safety passed {s['safety_passed']}. "
            f"Diagnostic: {s['diagnostic']}. Tool calls {s['tool_calls_total']}, "
            f"model calls {s['inference_calls_total']}.",
            "",
            "| case | expected | outcome | stop | score | safety | diagnostic | tools | model "
            "| top hypothesis |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for c in r["cases"]:
            top = (c.get("ranked") or [{}])[0]
            lead = f"{top.get('subsystem', '')} {top.get('confidence', '')}".strip()
            out.append(
                f"| {c['case_id']} | {c['expected']} | {c['outcome']} "
                f"| {c.get('stopping_reason', '')} | {c['total']} | {c['safety']} "
                f"| {c['diagnostic']} | {c['tool_calls']} | {c['inference_calls']} | {lead} |"
            )
        out.append("")
    return "\n".join(out) + "\n"


async def replay_async(args: argparse.Namespace) -> None:
    planner = ReplayPlanner(Path(args.replay))
    logged = PlannerLog(planner)
    result = await run(
        f"{args.label} {planner.name}",
        BoundedInvestigator(logged),
        planner,
        args.only or None,
        logged,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"{args.label}-replay.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(to_markdown([result]))


async def main_async(args: argparse.Namespace) -> None:
    if args.replay:
        await replay_async(args)
        return
    only = args.only or None
    suite_name = args.suite
    runs = [
        await run(
            f"{args.label} always-abstain stub",
            AlwaysAbstainInvestigator(),
            None,
            only,
            suite_name=suite_name,
        ),
    ]
    double = PlannerDouble()
    runs.append(
        await run(
            f"{args.label} planner double (no model)",
            BoundedInvestigator(double),
            double,
            only,
            suite_name=suite_name,
        )
    )
    if args.live:
        live = GeminiPlanner.from_env(cost_cap_usd=args.cost_cap)
        logged = PlannerLog(live)
        runs.append(
            await run(
                f"{args.label} live {live.name}",
                BoundedInvestigator(logged),
                live,
                only,
                logged,
                suite_name,
            )
        )
        runs[-1]["gemini"] = {
            "calls": live.calls,
            "tokens": live.tokens,
            "cost_usd": round(live.cost_usd, 6),
        }
    out = OUTPUT / "heldout" if suite_name == "heldout" else OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    names = ["stub-baseline", "planner-double", "live-gemini"]
    for run_, name in zip(runs, names, strict=False):
        (out / f"{args.label}-{name}.json").write_text(
            json.dumps(run_, indent=2, sort_keys=True) + "\n"
        )
    shown = [*runs, *(json.loads(Path(p).read_text()) for p in args.include)]
    (out / f"{args.label}-scorecard.md").write_text(to_markdown(shown))
    print(to_markdown(shown))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cost-cap", type=float, default=0.25)
    parser.add_argument("--suite", choices=["regression", "heldout"], default="regression")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--replay", help="a recorded live scorecard JSON whose plans to replay")
    parser.add_argument(
        "--include", nargs="*", default=[], help="recorded run JSON to append to the markdown"
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
