"""
Three incident cases where abstaining is the only correct answer. The trigger sounds
actionable in each. The evidence behind it does not support a root cause.
"""

from __future__ import annotations

from finsentry.investigator import fixtures as fx
from finsentry.investigator.contracts import AffectedScope, IncidentTrigger, TimeWindow
from finsentry.investigator.evaluation.types import GroundTruth, IncidentCase
from finsentry.investigator.evaluation.world import WorldData

WINDOW = TimeWindow(start=fx.at(60), end=fx.ANCHOR)


def unavailable_source() -> IncidentCase:
    """A block cluster is reported, but every RisingWave-backed tool is down. Nothing
    about the cluster can be read, so no cause can be named."""
    world = WorldData(
        drift=fx.drift_report(),
        unavailable=frozenset(
            {
                "get_failing_traces",
                "explain_guardrail_decision",
                "get_judge_scores",
                "search_prompt_injections",
                "search_traces",
                "get_trace_detail",
            }
        ),
    )
    truth = GroundTruth(
        expected_outcome="abstention",
        recipe=(("get_failing_traces", {"failure_type": "blocked", "time_window_minutes": 60}),),
        min_tool_calls=2,  # the call and one justified retry
        acceptable_tools=frozenset({"get_failing_traces", "get_drift_report"}),
        acceptable_stops=frozenset({"critical_evidence_unavailable", "justified_abstention"}),
    )
    return IncidentCase(
        "unavailable-source",
        "insufficient_evidence",
        "A faithfulness block cluster was reported and the trace source is unavailable.",
        IncidentTrigger(kind="faithfulness_block_cluster", description="blocks reported"),
        WINDOW,
        world,
        truth,
    )


def sparse_signal() -> IncidentCase:
    """Two blocked requests on different tickers and rails, a healthy judge, and Red Team
    executions that all behave as expected. There is no cluster to explain."""
    failing = (
        fx.failing_trace("sp-01", "guardrail_blocked", ticker="AAPL", block_rail="faithfulness"),
        fx.failing_trace(
            "sp-02", "guardrail_blocked", ticker="JPM", block_rail="check hazard taxonomy"
        ),
    )
    di = fx.execution(
        "rt-di-001",
        "DI-001",
        "direct_injection",
        outcome="caught",
        expected_caught_by="prompt-guard-2",
    )
    world = WorldData(failing=failing, drift=fx.drift_report(), executions=(di,))
    truth = GroundTruth(
        expected_outcome="abstention",
        recipe=(
            ("get_failing_traces", {"failure_type": "blocked", "time_window_minutes": 60}),
            ("get_drift_report", {}),
        ),
        min_tool_calls=2,
        acceptable_tools=frozenset({"get_failing_traces", "list_red_team_executions"}),
        acceptable_stops=frozenset({"justified_abstention"}),
    )
    return IncidentCase(
        "sparse-signal",
        "insufficient_evidence",
        "A cluster alert fired for two unrelated blocked requests.",
        IncidentTrigger(kind="faithfulness_block_cluster", description="blocks reported"),
        WINDOW,
        world,
        truth,
    )


def ambiguous_signal() -> IncidentCase:
    """Six NVDA disagreements. Three cite one chunk and three do not, and the judge drift
    reading sits between the entry and recovery thresholds. A retrieval cause and a judge
    cause fit equally, and nothing in the readable records separates them."""
    ids = [f"nv-{i:02d}" for i in range(1, 7)]
    items = [
        fx.trace_item(t, ticker="NVDA", frontier_sampled=True, minutes_ago=2 + i)
        for i, t in enumerate(ids)
    ]
    details = {
        t: fx.trace_detail(
            t,
            ticker="NVDA",
            chunks=["NVDA-10K-0210", "NVDA-10K-0011"] if i < 3 else ["NVDA-10K-0099"],
            flash_faithfulness=0.9,
            frontier_faithfulness=0.2,
            contradicting_chunks=["NVDA-10K-0210"] if i < 3 else [],
        )
        for i, t in enumerate(ids)
    }
    world = WorldData(
        trace_items=tuple(items),
        trace_details=details,
        disagreeing=frozenset(ids),
        drift=fx.drift_report(state="degraded", kappa=0.48),
    )
    truth = GroundTruth(
        expected_outcome="abstention",
        recipe=(
            ("search_traces", {"disagreement": True, "ticker": "NVDA"}),
            ("get_drift_report", {}),
        ),
        min_tool_calls=2,
        acceptable_tools=frozenset({"search_traces", "get_drift_report", "get_trace_detail"}),
        acceptable_stops=frozenset({"justified_abstention"}),
    )
    return IncidentCase(
        "ambiguous-signal",
        "insufficient_evidence",
        "Disagreement on NVDA fits both a retrieval cause and a judge cause equally.",
        IncidentTrigger(kind="judge_disagreement_cluster", description="disagreement on NVDA"),
        WINDOW,
        world,
        truth,
        AffectedScope(ticker="NVDA"),
    )
