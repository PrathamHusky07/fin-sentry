"""A prediction is judged by the query it concerns, never by another query's records.

Before this, build_diagnosis and the ledger evaluated every prediction over every result, so a
prediction about one endpoint, time window, scenario or sampled population could be satisfied
or contradicted by records from a different scope. These tests run the real loop over a
fixture world in which two queries of the same tool return opposite answers.
"""

from __future__ import annotations

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import IncidentTrigger, InvestigationResult
from finsentry.investigator.evaluation.planner_double import hypothesis, prediction
from finsentry.investigator.evaluation.world import FixtureWorld, WorldData
from finsentry.investigator.loop import BoundedInvestigator, start_investigation
from finsentry.investigator.planning import Plan
from tests.investigator.helpers import make_state


class Scripted:
    name = "scripted"
    cost_usd = 0.0

    def __init__(self, *plans: Plan) -> None:
        self.plans = list(plans)

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        return self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]


async def investigate(
    world: WorldData, plan: Plan, trigger: IncidentTrigger | None = None
) -> InvestigationResult:
    base = make_state()
    # A drift trigger states no block cluster, so a cluster is evidence of a mechanism here.
    default = IncidentTrigger(kind="drift_degradation", description="judge agreement fell")
    state = start_investigation("inc-scope", trigger or default, base.window)
    return await BoundedInvestigator(Scripted(plan)).investigate(
        state, ReadOnlyAdapter(FixtureWorld(world)), lambda: 0.0
    )


def status_of(result: InvestigationResult, hypothesis_id: str) -> str:
    return next(h.status for h in result.state.hypotheses if h.hypothesis_id == hypothesis_id)


def record_ids(result: InvestigationResult, hypothesis_id: str, side: str) -> set[str]:
    h = next(h for h in result.state.hypotheses if h.hypothesis_id == hypothesis_id)
    return {r.record_id for r in getattr(h, side)}


# Two endpoints, the same tool and the same signal, opposite answers.

A_BLOCKS = tuple(
    fx.failing_trace(
        f"a-{i}", "guardrail_blocked", endpoint="/rag/a", block_rail="faithfulness", minutes_ago=5
    )
    for i in range(6)
)
B_BLOCKS = (
    fx.failing_trace(
        "b-0", "guardrail_blocked", endpoint="/rag/b", block_rail="faithfulness", minutes_ago=5
    ),
)
ARGS_A = {"failure_type": "blocked", "endpoint": "/rag/a", "time_window_minutes": 60, "limit": 50}
ARGS_B = {"failure_type": "blocked", "endpoint": "/rag/b", "time_window_minutes": 60, "limit": 50}


def endpoint_plan() -> Plan:
    """h1 says the cluster is on /rag/a and not on /rag/b. h2 says the reverse."""

    def block(args: dict[str, object], *, expect: bool) -> object:
        return prediction(
            "get_failing_traces", "block_cluster", "blocks cluster", expect=expect, args=args
        )

    return Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "blocks",
                "output_rails",
                "The faithfulness rail misfires on /rag/a only.",
                block(ARGS_A, expect=True),  # type: ignore[arg-type]
                block(ARGS_B, expect=False),  # type: ignore[arg-type]
            ),
            hypothesis(
                "h2",
                "blocks",
                "retrieval",
                "Retrieval is faulty on /rag/b only.",
                block(ARGS_A, expect=False),  # type: ignore[arg-type]
                block(ARGS_B, expect=True),  # type: ignore[arg-type]
            ),
        ]
    )


async def test_two_endpoints_of_the_same_tool_do_not_contaminate_each_other() -> None:
    result = await investigate(WorldData(failing=(*A_BLOCKS, *B_BLOCKS)), endpoint_plan())
    assert status_of(result, "h1") == "supported"
    assert status_of(result, "h2") == "refuted"
    assert result.report.outcome == "diagnosis"
    assert result.report.ranked_hypotheses[0].hypothesis_id == "h1"


async def test_support_and_contradiction_cite_only_the_records_of_their_own_query() -> None:
    result = await investigate(WorldData(failing=(*A_BLOCKS, *B_BLOCKS)), endpoint_plan())
    a_ids = {t.app_trace_id for t in A_BLOCKS}
    b_ids = {t.app_trace_id for t in B_BLOCKS}
    # h1 predicted a cluster on /rag/a (met by a-*) and none on /rag/b (met by b-0).
    assert record_ids(result, "h1", "supporting") <= a_ids | b_ids
    assert not record_ids(result, "h1", "contradicting")
    # h2 is contradicted by each query's own records and by nothing else.
    assert record_ids(result, "h2", "contradicting") <= a_ids | b_ids
    assert record_ids(result, "h2", "contradicting") & a_ids


async def test_the_reverse_world_reverses_the_verdict() -> None:
    """The cluster is on /rag/b. If predictions read the union of both results, the answer
    would not change with the world."""
    a_small = tuple(
        fx.failing_trace(
            f"a-{i}", "guardrail_blocked", endpoint="/rag/a", block_rail="faithfulness"
        )
        for i in range(1)
    )
    b_big = tuple(
        fx.failing_trace(
            f"b-{i}", "guardrail_blocked", endpoint="/rag/b", block_rail="faithfulness"
        )
        for i in range(6)
    )
    result = await investigate(WorldData(failing=(*a_small, *b_big)), endpoint_plan())
    assert status_of(result, "h2") == "supported"
    assert status_of(result, "h1") == "refuted"


async def test_two_time_windows_of_the_same_tool_are_kept_apart() -> None:
    old = tuple(
        fx.failing_trace(
            f"old-{i}", "guardrail_blocked", block_rail="faithfulness", minutes_ago=50 + i
        )
        for i in range(6)
    )
    recent = (
        fx.failing_trace("new-0", "guardrail_blocked", block_rail="faithfulness", minutes_ago=2),
    )
    recent_args = {"failure_type": "blocked", "time_window_minutes": 10, "limit": 50}
    wide_args = {"failure_type": "blocked", "time_window_minutes": 60, "limit": 50}

    def block(args: dict[str, object], expect: bool) -> object:
        return prediction(
            "get_failing_traces", "block_cluster", "cluster", expect=expect, args=args
        )

    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "blocks",
                "output_rails",
                "A rail misfired recently.",
                block(recent_args, True),  # type: ignore[arg-type]
                block(wide_args, False),  # type: ignore[arg-type]
            ),
            hypothesis(
                "h2",
                "blocks",
                "retrieval",
                "The blocks are old and spread over the hour.",
                block(recent_args, False),  # type: ignore[arg-type]
                block(wide_args, True),  # type: ignore[arg-type]
            ),
        ]
    )
    result = await investigate(WorldData(failing=(*old, *recent)), plan)
    # 6 blocked in the hour is a cluster, and 1 in the last 10 minutes is not.
    assert status_of(result, "h2") == "supported"
    assert status_of(result, "h1") == "refuted"


# Red Team scenarios: a miss on one scenario must not satisfy a prediction about another.


async def test_a_miss_on_one_scenario_does_not_satisfy_a_prediction_about_another() -> None:
    miss = fx.execution(
        "rt-pii-1",
        "PII-001",
        "pii",
        outcome="missed",
        expected_caught_by="pii-redaction",
        target_layer="pii-redaction",
    )
    held = fx.execution(
        "rt-out-1",
        "OUT-001",
        "output_schema",
        outcome="caught",
        expected_caught_by="schema-enforcement",
        target_layer="schema-enforcement",
    )

    def regression(scenario: str, *, expect: bool) -> object:
        return prediction(
            "list_red_team_executions",
            "rail_regression",
            f"{scenario} was missed",
            expect=expect,
            args={"scenario_id": scenario, "limit": 20},
        )

    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "regression",
                "input_rails",
                "PII redaction regressed.",
                regression("PII-001", expect=True),  # type: ignore[arg-type]
                regression("OUT-001", expect=False),  # type: ignore[arg-type]
            ),
            hypothesis(
                "h2",
                "regression",
                "output_rails",
                "The output schema rail regressed.",
                regression("PII-001", expect=False),  # type: ignore[arg-type]
                regression("OUT-001", expect=True),  # type: ignore[arg-type]
            ),
        ]
    )
    trigger = IncidentTrigger(
        kind="red_team_miss", reference_id="rt-pii-1", description="PII-001 missed"
    )
    result = await investigate(WorldData(executions=(miss, held)), plan, trigger)
    assert status_of(result, "h1") == "supported"
    assert status_of(result, "h2") == "refuted"
    assert record_ids(result, "h1", "supporting") & {"rt-pii-1"}
    assert "rt-pii-1" not in record_ids(result, "h2", "supporting")


# Sampled trace details: two groups of sampled traces are two populations.


def _details(prefix: str, count: int, shared: str | None) -> dict[str, object]:
    out: dict[str, object] = {}
    for i in range(1, count + 1):
        chunks = [f"{prefix}-own-{i}"] + ([shared] if shared else [])
        out[f"{prefix}-{i}"] = fx.trace_detail(
            f"{prefix}-{i}", rag_status="blocked", chunks=chunks, block_rail="faithfulness"
        )
    return out


async def test_two_sampled_populations_are_not_pooled() -> None:
    a = tuple(
        fx.failing_trace(
            f"sa-{i}", "guardrail_blocked", endpoint="/rag/a", block_rail="faithfulness"
        )
        for i in range(1, 4)
    )
    b = tuple(
        fx.failing_trace(
            f"sb-{i}", "guardrail_blocked", endpoint="/rag/b", block_rail="faithfulness"
        )
        for i in range(1, 4)
    )
    details = {**_details("sa", 3, "C-SHARED"), **_details("sb", 3, None)}
    listing_a = ("get_failing_traces", {**ARGS_A, "limit": 10})
    listing_b = ("get_failing_traces", {**ARGS_B, "limit": 10})

    def shared(listing: tuple[str, dict[str, object]], *, expect: bool) -> object:
        return prediction(
            "get_trace_detail",
            "chunk_shared_by_failures",
            "failed traces share a chunk",
            expect=expect,
            listing=listing,  # type: ignore[arg-type]
            size=2,
        )

    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "blocks",
                "retrieval",
                "A chunk the /rag/a blocks share is faulty.",
                shared(listing_a, expect=True),  # type: ignore[arg-type]
                shared(listing_b, expect=False),  # type: ignore[arg-type]
            ),
            hypothesis(
                "h2",
                "blocks",
                "output_rails",
                "The rail misfires on /rag/b whatever was retrieved.",
                shared(listing_a, expect=False),  # type: ignore[arg-type]
                shared(listing_b, expect=True),  # type: ignore[arg-type]
            ),
        ]
    )
    world = WorldData(failing=(*a, *b), trace_details=details)  # type: ignore[arg-type]
    result = await investigate(world, plan)
    assert status_of(result, "h1") == "supported"
    assert status_of(result, "h2") == "refuted"


async def test_a_verified_empty_second_endpoint_is_absence_for_its_own_prediction_only() -> None:
    """/rag/a has a cluster and /rag/b returns a verified empty listing. The empty listing is
    the answer to the /rag/b predictions, and the /rag/a records answer the others."""
    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "blocks",
                "output_rails",
                "The rail misfires on /rag/b.",
                prediction(
                    "get_failing_traces",
                    "block_cluster",
                    "cluster on b",
                    args=ARGS_B,
                ),
                prediction(
                    "get_failing_traces",
                    "block_cluster",
                    "cluster on a",
                    expect=False,
                    args=ARGS_A,
                ),
            ),
            hypothesis(
                "h2",
                "blocks",
                "retrieval",
                "Retrieval is faulty on /rag/a.",
                prediction("get_failing_traces", "block_cluster", "cluster on a", args=ARGS_A),
                prediction(
                    "get_failing_traces",
                    "block_cluster",
                    "cluster on b",
                    expect=False,
                    args=ARGS_B,
                ),
            ),
        ]
    )
    result = await investigate(WorldData(failing=A_BLOCKS), plan)
    assert status_of(result, "h2") == "supported"
    assert status_of(result, "h1") == "refuted"
