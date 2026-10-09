"""Budget accounting, the repeat-query rule and the stopping rule."""

from __future__ import annotations

import pytest

from finsentry.investigator.contracts import (
    Budgets,
    EvidenceRef,
    ExecutedQuery,
    InvestigationState,
    ToolStatus,
)
from finsentry.investigator.policy import (
    PolicyViolationError,
    admit_inference,
    admit_query,
    critical_unavailable,
    decide_stop,
    finish,
    next_query_id,
    record_hypothesis_round,
    record_inference,
    record_query,
    with_elapsed,
)
from tests.investigator.helpers import make_hypothesis, make_state

TRACE = EvidenceRef(kind="trace", record_id="t1")


def _query(
    state: InvestigationState,
    tool: str = "get_failing_traces",
    status: ToolStatus = "ok",
    justification: str | None = None,
    **args: object,
) -> ExecutedQuery:
    return ExecutedQuery(
        query_id=next_query_id(state),
        tool=tool,  # type: ignore[arg-type]
        args=dict(args),
        status=status,
        evidence=[TRACE] if status == "ok" else [],
        retry_justification=justification,
    )


def _run(state: InvestigationState, **kw: object) -> InvestigationState:
    return record_query(state, _query(state, **kw), 1.0)  # type: ignore[arg-type]


def test_the_starting_ceilings_are_the_documented_ones() -> None:
    b = make_state().budgets
    assert (b.max_tool_calls, b.max_inference_calls, b.max_hypothesis_rounds) == (8, 2, 3)


def test_each_query_is_counted_and_gets_the_next_id() -> None:
    state = make_state()
    state = _run(state, limit=1)
    state = _run(state, limit=2)
    assert state.usage.tool_calls == 2
    assert [q.query_id for q in state.executed_queries] == ["q1", "q2"]


def test_the_ninth_tool_call_is_refused_and_the_budget_stops_the_run() -> None:
    state = make_state()
    for i in range(8):
        state = _run(state, limit=i + 1)
    refusal = admit_query(state, "get_failing_traces", {"limit": 99})
    assert not refusal.allowed and "tool_calls" in refusal.reason
    with pytest.raises(PolicyViolationError, match="tool_calls"):
        record_query(state, _query(state, limit=99), 1.0)
    assert decide_stop(state) == "budget_exhausted"


def test_the_wall_clock_ceiling_refuses_further_calls() -> None:
    state = with_elapsed(make_state(budgets=Budgets(max_wall_clock_s=10.0)), 10.0)
    assert "wall_clock" in admit_query(state, "get_drift_report", {}).reason
    assert decide_stop(state) == "budget_exhausted"


def test_wall_clock_only_moves_forward() -> None:
    state = with_elapsed(make_state(), 5.0)
    assert with_elapsed(state, 2.0).usage.wall_clock_s == 5.0


def test_inference_calls_stop_at_the_ceiling() -> None:
    state = make_state()
    state = record_inference(record_inference(state))
    assert not admit_inference(state).allowed
    with pytest.raises(PolicyViolationError):
        record_inference(state)
    assert decide_stop(state) == "budget_exhausted"


def test_hypothesis_rounds_stop_at_the_ceiling() -> None:
    state = make_state()
    for _ in range(3):
        state = record_hypothesis_round(state, [make_hypothesis()])
    assert state.usage.hypothesis_rounds == 3
    with pytest.raises(PolicyViolationError):
        record_hypothesis_round(state, [make_hypothesis()])


def test_an_identical_query_is_refused_whatever_the_key_order() -> None:
    state = _run(make_state(), limit=5, endpoint="/rag/query")
    again = admit_query(state, "get_failing_traces", {"endpoint": "/rag/query", "limit": 5})
    assert not again.allowed and "q1" in again.reason
    assert admit_query(state, "get_failing_traces", {"limit": 6}).allowed


def test_an_empty_result_is_not_a_reason_to_repeat_the_query() -> None:
    state = _run(make_state(), status="empty", limit=5)
    assert not admit_query(state, "get_failing_traces", {"limit": 5}, "try again").allowed


def test_an_unavailable_query_is_retried_only_with_a_justification() -> None:
    state = _run(make_state(), status="unavailable", limit=5)
    assert not admit_query(state, "get_failing_traces", {"limit": 5}).allowed
    assert not admit_query(state, "get_failing_traces", {"limit": 5}, "  ").allowed
    ok = admit_query(state, "get_failing_traces", {"limit": 5}, "RisingWave reconnected")
    assert ok.allowed
    retried = _run(state, status="ok", justification="RisingWave reconnected", limit=5)
    assert retried.usage.tool_calls == 2  # a retry spends budget like any call


def test_a_rejected_query_is_never_retried_unchanged() -> None:
    state = _run(make_state(), status="rejected", limit=500)
    assert not admit_query(state, "get_failing_traces", {"limit": 500}, "please").allowed


def test_skipping_the_admission_check_cannot_record_a_repeat() -> None:
    state = _run(make_state(), limit=5)
    with pytest.raises(PolicyViolationError, match="identical"):
        record_query(state, _query(state, limit=5), 1.0)


def test_a_tool_outside_the_nine_is_refused() -> None:
    assert not admit_query(make_state(), "run_red_team_scenario", {}).allowed


def test_a_stopped_investigation_admits_nothing() -> None:
    state = finish(make_state(), "justified_abstention")
    assert not admit_query(state, "get_drift_report", {}).allowed
    assert not admit_inference(state).allowed
    with pytest.raises(PolicyViolationError):
        finish(state, "budget_exhausted")


def test_critical_evidence_is_unavailable_after_the_first_call_and_a_retry() -> None:
    state = _run(make_state(), status="unavailable", limit=5)
    assert critical_unavailable(state) == []  # one failure may be a blip
    state = _run(state, status="unavailable", justification="retry once", limit=5)
    assert critical_unavailable(state) == ["get_failing_traces"]
    assert decide_stop(state) == "critical_evidence_unavailable"


def test_critical_evidence_that_ran_once_is_not_unavailable() -> None:
    state = _run(make_state(), status="unavailable", limit=5)
    state = _run(state, status="empty", justification="retry", limit=5)
    assert critical_unavailable(state) == []


def test_a_non_critical_tool_being_unavailable_does_not_stop_the_run() -> None:
    state = _run(make_state(), tool="get_drift_report", status="unavailable")
    state = _run(state, tool="get_drift_report", status="unavailable", justification="retry")
    assert critical_unavailable(state) == []
    assert decide_stop(state) is None


def test_the_stopping_rule_fires_in_precedence_order() -> None:
    state = make_state()
    assert decide_stop(state) is None
    assert decide_stop(state, abstain=True) == "justified_abstention"
    assert decide_stop(state, evidence_sufficient=True, abstain=True) == "sufficient_evidence"
    exhausted = with_elapsed(state, 500.0)
    assert decide_stop(exhausted) == "budget_exhausted"
    assert decide_stop(exhausted, evidence_sufficient=True) == "sufficient_evidence"
    stuck = _run(state, status="unavailable", limit=5)
    stuck = _run(stuck, status="unavailable", justification="retry", limit=5)
    assert decide_stop(stuck, evidence_sufficient=True) == "critical_evidence_unavailable"
