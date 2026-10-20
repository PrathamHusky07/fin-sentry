"""
A deterministic planner double: plays the model's part from the digest alone.

It exists to test the loop's orchestration (validation, query selection, the ledger, the
adversarial review, the timeouts and the report) without a model. It reads only the digest
the real planner would read, never a case's cause. It is not evidence of a model's diagnostic
quality, and a scorecard row made with it says so. The playbooks below are the standard rival
sets for each trigger, written the way a careful on-call engineer would list them. A query is
only run when two hypotheses make explicit, different predictions about it (planning.py), so
each playbook gives a rival the prediction that would make the other wrong.
"""

from __future__ import annotations

import json
from typing import Any

from finsentry.investigator.contracts import Signal, Subsystem, ToolName
from finsentry.investigator.planning import Plan, PlanHypothesis, PlanPrediction, QuerySpec

SCENARIO_SUBSYSTEM: dict[str, Subsystem] = {
    "DI": "input_rails",
    "MS": "input_rails",
    "HZ": "input_rails",
    "PII": "input_rails",
    "IND": "retrieval",
    "OUT": "output_rails",
    "GAP": "output_rails",
}


def prediction(
    tool: ToolName,
    signal: Signal,
    description: str,
    *,
    expect: bool = True,
    args: dict[str, Any] | None = None,
    sample_from: str | None = None,
    listing: tuple[ToolName, dict[str, Any]] | None = None,
    size: int = 2,
    sample_class: str | None = None,
) -> PlanPrediction:
    return PlanPrediction(
        query=QuerySpec(
            tool=tool,
            args_json=json.dumps(args or {}),
            sample_from=sample_from,
            listing_tool=listing[0] if listing else None,
            listing_args_json=json.dumps(listing[1]) if listing else "{}",
            sample_size=size,
            sample_class=sample_class,
        ),
        signal=signal,
        expect=expect,
        description=description,
    )


def hypothesis(
    hid: str, symptom: str, subsystem: Subsystem, statement: str, *preds: PlanPrediction
) -> PlanHypothesis:
    return PlanHypothesis(
        hypothesis_id=hid,
        symptom=symptom,
        subsystem=subsystem,
        statement=statement,
        predictions=list(preds),
    )


def _failures(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    counts = q1["facts"].get("classification_counts", {})
    same = dict(q1["args"])
    hyps: list[PlanHypothesis] = []
    if counts.get("guardrail_blocked"):
        cluster = prediction(
            "get_failing_traces", "block_cluster", "blocks cluster on one rail", args=same
        )
        shared = dict(sample_from=q1["query_id"], size=size, sample_class="guardrail_blocked")
        hyps += [
            hypothesis(
                "h1",
                "blocks",
                "retrieval",
                "A retrieved chunk that the blocked requests share is faulty.",
                cluster,
                prediction(
                    "get_trace_detail",
                    "chunk_shared_by_failures",
                    "blocked requests retrieved the same chunk",
                    **shared,
                ),
            ),
            hypothesis(
                "h2",
                "blocks",
                "output_rails",
                "The blocking rail misfires whatever was retrieved.",
                cluster,
                prediction(
                    "get_trace_detail",
                    "chunk_shared_by_failures",
                    "blocked requests share no chunk",
                    expect=False,
                    **shared,
                ),
            ),
        ]
    if counts.get("judge_pipeline_failure"):
        hyps += [
            hypothesis(
                "h3",
                "judge_failures",
                "judges",
                "The flash judge pipeline is failing on delivered answers.",
                prediction(
                    "get_failing_traces", "judge_failures", "judge failures cluster", args=same
                ),
            ),
            hypothesis(
                "h4",
                "judge_failures",
                "event_pipeline",
                "Verdict events are lost before the judge scores them.",
                prediction(
                    "get_failing_traces",
                    "judge_failures",
                    "no judge failures",
                    expect=False,
                    args=same,
                ),
            ),
        ]
    return hyps


def _disagreement(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    ticker = d["incident"]["scope"].get("ticker")
    agreeing = {"disagreement": False, "limit": 20, **({"ticker": ticker} if ticker else {})}
    sampled: dict[str, Any] = dict(sample_from=q1["query_id"], size=size)
    peers: dict[str, Any] = dict(listing=("search_traces", agreeing), size=size)
    return [
        hypothesis(
            "h1",
            "tier_disagreement",
            "retrieval",
            "One retrieved chunk the frontier judge contradicts is faulty.",
            prediction(
                "get_trace_detail",
                "chunk_contradicted",
                "the chunk is flagged on disagreeing traces",
                **sampled,
            ),
            prediction(
                "get_trace_detail",
                "chunk_contradicted",
                "no agreeing trace retrieved it",
                **peers,
            ),
            prediction("get_drift_report", "judge_drift", "the reading is healthy", expect=False),
        ),
        hypothesis(
            "h2",
            "tier_disagreement",
            "judges",
            "The frontier judge has drifted.",
            prediction("get_drift_report", "judge_drift", "the reading is drifted"),
            prediction(
                "get_trace_detail",
                "chunk_contradicted",
                "no one chunk explains the disagreement",
                expect=False,
                **sampled,
            ),
            prediction(
                "get_trace_detail",
                "chunk_contradicted",
                "agreeing traces retrieved the chunk too",
                expect=False,
                **peers,
            ),
        ),
    ]


def _red_team_miss(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    execution = q1["facts"].get("execution") or {}
    scenario = execution.get("scenario", "")
    subsystem = SCENARIO_SUBSYSTEM.get(scenario.split("-")[0], "input_rails")
    listing = {"scenario_id": scenario, "limit": 10}
    return [
        hypothesis(
            "h1",
            "missed_attack",
            subsystem,
            "A defense that caught this scenario earlier has stopped catching it.",
            prediction(
                "list_red_team_executions",
                "rail_regression",
                "the scenario now misses",
                args=listing,
            ),
        ),
        hypothesis(
            "h2",
            "missed_attack",
            subsystem,
            "The miss is isolated and the defense still works.",
            prediction(
                "list_red_team_executions",
                "rail_working",
                "the scenario is caught as expected",
                args=listing,
            ),
        ),
    ]


def _single_trace(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    facts, ref = q1["facts"], d["incident"]["reference_id"]
    window = d["incident"]["window_minutes"]
    if facts.get("judge_state") == "judge_failed":
        anyf = {"time_window_minutes": window, "failure_type": "any", "limit": 50}
        return [
            hypothesis(
                "h1",
                "trace_failure",
                "judges",
                "The flash judge pipeline is failing.",
                prediction(
                    "get_failing_traces", "judge_failures", "judge failures cluster", args=anyf
                ),
                prediction(
                    "get_judge_scores",
                    "judge_failures",
                    "this trace's verdict failed",
                    args={"app_trace_id": ref},
                ),
            ),
            hypothesis(
                "h2",
                "trace_failure",
                "input_rails",
                "An input rail is blocking requests.",
                prediction(
                    "get_failing_traces", "block_cluster", "blocks cluster on one rail", args=anyf
                ),
            ),
            hypothesis(
                "h3",
                "trace_failure",
                "event_pipeline",
                "Requests are failing inside the pipeline.",
                prediction(
                    "get_failing_traces", "error_cluster", "system errors cluster", args=anyf
                ),
                prediction(
                    "get_judge_scores",
                    "judge_failures",
                    "this trace has no failed verdict",
                    expect=False,
                    args={"app_trace_id": ref},
                ),
            ),
        ]
    if "injection" in (facts.get("block_rail") or ""):
        executions = {"category": "direct_injection", "limit": 5}
        return [
            hypothesis(
                "h1",
                "blocked_request",
                "input_rails",
                "A burst of injection attempts is being blocked by the input rail.",
                prediction(
                    "search_prompt_injections",
                    "injection_surge",
                    "many injection blocks",
                    args={"time_window_minutes": window, "limit": 50},
                ),
                prediction(
                    "list_red_team_executions",
                    "rail_working",
                    "the injection scenario is caught",
                    args=executions,
                ),
            ),
            hypothesis(
                "h2",
                "blocked_request",
                "input_rails",
                "The injection rail is failing to catch attacks.",
                prediction(
                    "list_red_team_executions",
                    "rail_regression",
                    "an injection scenario now misses",
                    args=executions,
                ),
                prediction(
                    "search_prompt_injections",
                    "injection_surge",
                    "few injection blocks, since attacks get through",
                    expect=False,
                    args={"time_window_minutes": window, "limit": 50},
                ),
            ),
        ]
    return _failures(
        d,
        {
            **q1,
            "facts": {"classification_counts": {"guardrail_blocked": 1}},
            "args": {"time_window_minutes": window, "failure_type": "any", "limit": 50},
        },
        size,
    )


def _error_surge(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    same = dict(q1["args"])
    return [
        hypothesis(
            "h1",
            "errors",
            "event_pipeline",
            "One error kind is failing requests inside the pipeline.",
            prediction("get_failing_traces", "error_cluster", "errors share a kind", args=same),
        ),
        hypothesis(
            "h2",
            "errors",
            "downstream_model",
            "The downstream model is failing requests.",
            prediction(
                "get_failing_traces",
                "error_cluster",
                "errors do not cluster",
                expect=False,
                args=same,
            ),
        ),
    ]


def _drift(d: dict[str, Any], q1: dict[str, Any], size: int) -> list[PlanHypothesis]:
    return [
        hypothesis(
            "h1",
            "drift",
            "judges",
            "The frontier judge has drifted.",
            prediction("get_drift_report", "judge_drift", "the reading is drifted"),
        ),
        hypothesis(
            "h2",
            "drift",
            "retrieval",
            "The judge is fine and the inputs changed.",
            prediction("get_drift_report", "judge_drift", "the reading is healthy", expect=False),
        ),
    ]


PLAYBOOKS = {
    "faithfulness_block_cluster": _failures,
    "judge_disagreement_cluster": _disagreement,
    "red_team_miss": _red_team_miss,
    "single_trace": _single_trace,
    "error_kind_surge": _error_surge,
    "drift_degradation": _drift,
}


class PlannerDouble:
    name = "planner-double"
    cost_usd = 0.0

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        d = json.loads(digest)
        opening = d["executed_queries"][0]
        size = 2 if round_no == 1 else 3  # a second look widens the sample
        hypotheses = PLAYBOOKS[d["incident"]["trigger"]](d, opening, size)
        return Plan(hypotheses=hypotheses)
