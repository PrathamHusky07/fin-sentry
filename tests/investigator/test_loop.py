"""The bounded investigator: it diagnoses what its evidence supports, abstains when it
cannot, challenges its own leader, stays inside its budgets and cancels a call that hangs.

Most tests use the deterministic planner double, which tests orchestration and contracts. It
says nothing about how a model plans."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import Budgets, InvestigationResult, ToolName
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.planner_double import (
    PlannerDouble,
    hypothesis,
    prediction,
)
from finsentry.investigator.evaluation.runner import run_case
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld, WorldData
from finsentry.investigator.loop import (
    BoundedInvestigator,
    InvestigationFailedError,
    merge_hypotheses,
    spread,
    start_investigation,
)
from finsentry.investigator.planning import Plan, PlanningError
from tests.investigator.helpers import make_hypothesis

CASES = {c.case_id: c for c in all_cases()}
EXPECTED_STOP = {
    "unavailable-source": "critical_evidence_unavailable",
    "sparse-signal": "justified_abstention",
    "ambiguous-signal": "justified_abstention",
}


class Scripted:
    """A planner that returns the plans it was given, or raises the exceptions it was given."""

    name = "scripted"
    cost_usd = 0.0

    def __init__(self, *plans: Plan | Exception) -> None:
        self.plans = list(plans)
        self.digests: list[str] = []

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        self.digests.append(digest)
        item = self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]
        if isinstance(item, Exception):
            raise item
        return item


async def investigate(
    case: IncidentCase,
    planner: Any,
    *,
    world: FixtureWorld | None = None,
    budgets: Budgets | None = None,
    probe: bool = True,
    **investigator: Any,
) -> InvestigationResult:
    world = world or FixtureWorld(case.world)
    state = start_investigation(
        f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope, budgets=budgets
    )
    adapter = ReadOnlyAdapter(
        world, failure_probe=(lambda: world.failed_query_count) if probe else None
    )
    return await BoundedInvestigator(planner, **investigator).investigate(
        state, adapter, time.monotonic
    )


# What it does on the nine known-answer cases (with the planner double).


@pytest.mark.parametrize("case", list(CASES.values()), ids=lambda c: c.case_id)
async def test_it_diagnoses_what_it_can_and_abstains_when_it_cannot(case: IncidentCase) -> None:
    result = await investigate(case, PlannerDouble())
    report, state = result.report, result.state
    assert validate_report(report, state).valid
    assert report.outcome == case.truth.expected_outcome
    if case.case_id in EXPECTED_STOP:
        assert report.stopping_reason == EXPECTED_STOP[case.case_id]
    if report.outcome == "diagnosis":
        top = min(report.ranked_hypotheses, key=lambda h: h.rank)
        assert top.subsystem in case.truth.true_subsystems
        assert report.causal_claims == [], "the production cause stays a hypothesis"
        assert report.correlations and all(
            "Consistent with" in c.statement for c in report.correlations
        )


@pytest.mark.parametrize("case", list(CASES.values()), ids=lambda c: c.case_id)
async def test_every_case_stays_inside_its_budgets_and_repeats_no_query(case: IncidentCase) -> None:
    result = await investigate(case, PlannerDouble())
    u, b = result.state.usage, result.state.budgets
    assert u.tool_calls <= b.max_tool_calls
    assert u.inference_calls <= b.max_inference_calls
    assert u.hypothesis_rounds <= b.max_hypothesis_rounds
    seen: dict[tuple[str, str], str] = {}
    for q in result.state.executed_queries:
        key = (q.tool, json.dumps(q.args, sort_keys=True))
        if key in seen:  # only a justified retry of an unavailable query may repeat
            assert seen[key] == "unavailable" and q.retry_justification
        seen[key] = q.status


async def test_the_misleading_case_names_the_judge_and_records_the_agreeing_traces() -> None:
    result = await investigate(CASES["drifted-judge-misleading"], PlannerDouble())
    top = min(result.report.ranked_hypotheses, key=lambda h: h.rank)
    assert top.subsystem == "judges" and "gemini-rubric" in top.statement
    retrieval = next(h for h in result.report.ranked_hypotheses if h.subsystem == "retrieval")
    assert any(r.record_id.startswith("agree-") for r in retrieval.contradicting)
    assert any(a.hypothesis_id == retrieval.hypothesis_id for a in result.report.evidence_against)


async def test_a_confident_diagnosis_needs_a_rival_refuted_by_a_record() -> None:
    stale = await investigate(CASES["stale-chunk"], PlannerDouble())
    outage = await investigate(CASES["judge-outage"], PlannerDouble())
    assert min(stale.report.ranked_hypotheses, key=lambda h: h.rank).confidence == "high"
    assert min(outage.report.ranked_hypotheses, key=lambda h: h.rank).confidence != "high"


# It receives only the trigger, scope, window and tool results.


@pytest.mark.parametrize(
    "case_id, hidden",
    [
        ("drifted-judge-misleading", ["MSFT-10K-0301", "gemini-rubric"]),
        ("stale-chunk", ["AMZN-10K-0412"]),
        ("retrieval-and-judge", ["META-10Q-0077"]),
    ],
)
async def test_the_first_digest_holds_none_of_the_seeded_cause(
    case_id: str, hidden: list[str]
) -> None:
    planner = Scripted(await PlannerDouble().plan(await _first_digest(CASES[case_id]), round_no=1))
    await investigate(CASES[case_id], planner)
    for needle in hidden:
        assert needle not in planner.digests[0], needle


async def _first_digest(case: IncidentCase) -> str:
    captured: list[str] = []

    class Capture(PlannerDouble):
        async def plan(self, digest: str, *, round_no: int) -> Plan:
            captured.append(digest)
            return await super().plan(digest, round_no=round_no)

    await investigate(case, Capture())
    return captured[0]


# It picks queries because they separate hypotheses.


async def test_every_query_after_the_opening_records_what_it_separates() -> None:
    result = await investigate(CASES["drifted-judge-misleading"], PlannerDouble())
    opening, *rest = result.state.executed_queries
    assert opening.separates == []
    assert rest and all(len(q.separates) >= 2 for q in rest)


async def test_a_query_every_hypothesis_predicts_the_same_way_is_never_run() -> None:
    case = CASES["judge-outage"]
    same = prediction("get_drift_report", "judge_drift", "the reading is drifted")
    other = prediction(
        "get_failing_traces",
        "judge_failures",
        "failures cluster",
        args={"time_window_minutes": 60, "failure_type": "any", "limit": 50},
    )
    plan = Plan(
        hypotheses=[
            hypothesis("h1", "x", "judges", "judges fail", same, other),
            hypothesis("h2", "x", "retrieval", "retrieval fails", same),
        ]
    )
    result = await investigate(case, Scripted(plan))
    run = [q.tool for q in result.state.executed_queries]
    assert "get_drift_report" not in run, "both hypotheses predict it identically"
    assert "get_failing_traces" in run


async def test_a_plan_that_leaves_the_tool_surface_is_cut_down_or_refused() -> None:
    case = CASES["judge-outage"]
    wrong_tool = prediction("get_drift_report", "judge_failures", "wrong tool for the signal")
    bad_args = prediction("get_failing_traces", "judge_failures", "bad limit", args={"limit": 0})
    plan = Plan(
        hypotheses=[
            hypothesis("h1", "x", "judges", "judges fail", wrong_tool),
            hypothesis("h2", "x", "retrieval", "retrieval fails", bad_args),
        ]
    )
    result = await investigate(case, Scripted(plan))
    assert result.report.outcome == "abstention"
    assert result.state.stopping_reason == "budget_exhausted"
    assert result.state.usage.tool_calls == 1, "only the opening query ran"
    assert result.state.usage.inference_calls == 2, "the repair call was tried and also failed"


# A later plan replaces a hypothesis it names again and may add new ones.


def test_merging_hypotheses_keeps_ids_stable_and_caps_the_ledger() -> None:
    old = [make_hypothesis("h1"), make_hypothesis("h2")]
    new = [
        make_hypothesis("h2", statement="revised"),
        make_hypothesis("h3"),
        make_hypothesis("h4"),
        make_hypothesis("h5"),
    ]
    merged = merge_hypotheses(old, new)
    assert [h.hypothesis_id for h in merged] == ["h1", "h2", "h3", "h4"]
    assert next(h for h in merged if h.hypothesis_id == "h2").statement == "revised"


def test_a_sample_is_spread_across_a_listing_not_taken_from_its_head() -> None:
    ids = [f"t{i}" for i in range(10)]
    assert spread(ids, 2) == ["t0", "t9"]
    assert spread(ids, 3) == ["t0", "t4", "t9"] or spread(ids, 3) == ["t0", "t5", "t9"]
    assert spread(ids, 1) == ["t0"] and spread(ids[:2], 3) == ids[:2]


# Adversarial review.


async def test_two_supported_rivals_force_a_second_look_then_an_abstention() -> None:
    case = CASES["judge-outage"]
    anyf = {"time_window_minutes": 60, "failure_type": "any", "limit": 50}
    judged = {"time_window_minutes": 60, "failure_type": "judge_failed", "limit": 50}
    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "failure",
                "judges",
                "judges fail",
                prediction("get_failing_traces", "judge_failures", "failures cluster", args=anyf),
            ),
            hypothesis(
                "h2",
                "failure",
                "event_pipeline",
                "events are lost",
                prediction("get_failing_traces", "judge_failures", "failures cluster", args=judged),
            ),
        ]
    )
    planner = Scripted(plan)
    result = await investigate(case, planner)
    assert result.report.outcome == "abstention"
    assert result.state.usage.inference_calls == 2, "the conflict bought one more look"
    assert any("each supported for the same symptom" in m for m in result.report.missing_evidence)


async def test_a_leader_with_a_prediction_it_could_not_check_is_not_reported() -> None:
    case = CASES["judge-outage"]
    anyf = {"time_window_minutes": 60, "failure_type": "any", "limit": 50}
    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "failure",
                "judges",
                "judges fail",
                prediction("get_failing_traces", "judge_failures", "failures cluster", args=anyf),
                prediction(
                    "list_red_team_executions",
                    "rail_working",
                    "a scenario is caught",
                    args={"limit": 5},
                ),
            ),
            hypothesis(
                "h2",
                "failure",
                "input_rails",
                "an input rail blocks",
                prediction("get_failing_traces", "block_cluster", "blocks cluster", args=anyf),
            ),
        ]
    )
    result = await investigate(case, Scripted(plan))
    assert result.report.outcome == "abstention"
    assert any("could not check" in n for n in result.report.limitations)


async def test_a_diagnosis_says_what_its_review_did_and_did_not_establish() -> None:
    result = await investigate(CASES["stale-chunk"], PlannerDouble())
    assert any(note.startswith("Challenge of h1") for note in result.report.limitations)
    assert any("does not prove the cause" in note for note in result.report.limitations)


async def test_a_diagnosis_that_fails_validation_becomes_an_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finsentry.investigator import loop
    from finsentry.investigator.contracts import Claim, EvidenceRef

    real = loop.build_diagnosis

    def forged(*args: Any, **kwargs: Any) -> Any:
        report = real(*args, **kwargs)
        ghost = EvidenceRef(kind="trace", record_id="never-retrieved")
        forged_claim = Claim(statement="x", evidence=[ghost])
        return report.model_copy(update={"observations": [forged_claim]})

    monkeypatch.setattr(loop, "build_diagnosis", forged)
    result = await investigate(CASES["stale-chunk"], PlannerDouble())
    assert result.report.outcome == "abstention"
    assert result.state.stopping_reason == "justified_abstention"
    assert any("failed validation" in n for n in result.report.limitations)


# An empty result that may be a failed query is not a clean signal.


@pytest.mark.parametrize("probe", [True, False])
async def test_a_failed_injection_search_is_never_read_as_no_surge(probe: bool) -> None:
    base = CASES["injection-surge"]
    world = FixtureWorld(
        WorldData(
            **{**base.world.__dict__, "failing_queries": frozenset({"search_prompt_injections"})}
        )
    )
    result = await investigate(base, PlannerDouble(), world=world, probe=probe)
    assert result.report.outcome == "abstention", (
        "the surge cannot be established without the search"
    )
    search = next(q for q in result.state.executed_queries if q.tool == "search_prompt_injections")
    assert (search.status, search.empty_unverified) == (
        ("unavailable", False) if probe else ("empty", True)
    )
    assert any(
        "search_prompt_injections" in m or "injection_surge" in m
        for m in result.report.missing_evidence
    )


# Time and failure.


async def test_unavailable_critical_evidence_ends_the_run_with_no_model_call() -> None:
    result = await investigate(CASES["unavailable-source"], PlannerDouble())
    assert result.state.usage.inference_calls == 0 and result.state.usage.tool_calls == 2
    assert result.report.stopping_reason == "critical_evidence_unavailable"
    assert (
        result.report.tool_unavailable == ["get_failing_traces"]
        and result.report.empty_results == []
    )


async def test_a_hung_tool_call_is_cancelled_and_recorded_not_waited_on() -> None:
    cancelled = asyncio.Event()

    class Hangs(FixtureWorld):
        async def get_failing_traces(self, *a: Any, **k: Any) -> Any:
            try:
                await asyncio.sleep(3600)
            finally:
                cancelled.set()

    case = CASES["sparse-signal"]
    started = time.monotonic()
    result = await investigate(
        case, PlannerDouble(), world=Hangs(case.world), budgets=Budgets(max_wall_clock_s=0.4)
    )
    assert time.monotonic() - started < 3.0
    assert cancelled.is_set(), "the hung call was cancelled"
    first = result.state.executed_queries[0]
    assert first.status == "unavailable" and "timed out" in (first.error or "")
    assert result.report.outcome == "abstention"
    assert result.state.stopping_reason in ("budget_exhausted", "critical_evidence_unavailable")


async def test_a_hung_model_call_is_cancelled_and_the_run_ends_honestly() -> None:
    cancelled = asyncio.Event()

    class HungPlanner:
        name = "hung"
        cost_usd = 0.0

        async def plan(self, digest: str, *, round_no: int) -> Plan:
            try:
                await asyncio.sleep(3600)
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    started = time.monotonic()
    result = await investigate(CASES["stale-chunk"], HungPlanner(), model_timeout_s=0.2)
    assert time.monotonic() - started < 3.0 and cancelled.is_set()
    assert result.report.outcome == "abstention"
    assert result.state.stopping_reason == "budget_exhausted"
    assert result.state.usage.inference_calls == 2
    assert any("timed out" in n for n in result.report.limitations)


async def test_a_planner_that_raises_is_a_recorded_abstention() -> None:
    result = await investigate(CASES["stale-chunk"], Scripted(PlanningError("no plan")))
    assert result.report.outcome == "abstention" and result.state.usage.inference_calls == 2


async def test_a_crash_carries_the_spend_so_far(monkeypatch: pytest.MonkeyPatch) -> None:
    from finsentry.investigator import loop

    def explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("ledger bug")

    monkeypatch.setattr(loop, "assess", explode)
    with pytest.raises(InvestigationFailedError) as caught:
        await investigate(CASES["stale-chunk"], PlannerDouble())
    assert caught.value.state.usage.inference_calls == 1
    assert caught.value.state.usage.tool_calls >= 1
    score = await run_case(BoundedInvestigator(PlannerDouble()), CASES["stale-chunk"], lambda: 0.0)
    assert (
        score.actual_outcome == "no_report" and score.inference_calls == 1 and score.tool_calls >= 1
    )


async def test_it_reaches_the_world_only_through_the_nine_read_tools() -> None:
    world = FixtureWorld(CASES["retrieval-and-judge"].world)
    await investigate(CASES["retrieval-and-judge"], PlannerDouble(), world=world)
    from finsentry.investigator.contracts import TOOL_NAMES

    names: list[ToolName] = [name for name, _ in world.calls]  # type: ignore[misc]
    assert names and set(names) <= set(TOOL_NAMES)


async def test_without_the_agreeing_trace_test_the_misleading_case_ends_in_abstention() -> None:
    """A plan that samples only the disagreeing traces leaves the retrieval and judge
    explanations both supported. The loop does not pick the symptom's subsystem. It abstains."""
    case = CASES["drifted-judge-misleading"]
    plan = Plan(
        hypotheses=[
            hypothesis(
                "h1",
                "tier_disagreement",
                "retrieval",
                "A retrieved chunk is faulty.",
                prediction("get_trace_detail", "chunk_contradicted", "flagged", sample_from="q1"),
            ),
            hypothesis(
                "h2",
                "tier_disagreement",
                "judges",
                "The frontier judge has drifted.",
                prediction("get_drift_report", "judge_drift", "drifted"),
            ),
        ]
    )
    result = await investigate(case, Scripted(plan))
    assert result.report.outcome == "abstention"
    assert any("each supported for the same symptom" in m for m in result.report.missing_evidence)
    score = await run_case(BoundedInvestigator(Scripted(plan)), case, lambda: 0.0)
    assert score.safety_pass and score.diagnostic == "incomplete"
