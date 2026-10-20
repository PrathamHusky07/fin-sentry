"""Evidence integrity in the signal evaluators.

An unverified empty is never negative evidence, a prediction is checked against the subject it
names and never a substitute, drift history can be read without a current reading, and a
finding cannot establish a diagnosis in a subsystem its records cannot bear on.
"""

from __future__ import annotations

from typing import get_args

import pytest

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import (
    Hypothesis,
    PredictedObservation,
    Signal,
    Subsystem,
    ToolName,
)
from finsentry.investigator.ledger import assess, review
from finsentry.investigator.signals import evaluate
from finsentry.mcp.tools.drift import TransitionRecordSummary
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import GetFailingTracesResult
from finsentry.redteam.models import Rail


def result(
    tool: ToolName,
    payload: object,
    *,
    status: str = "ok",
    unverified: bool = False,
    **args: object,
) -> ToolResult:
    return ToolResult("q1", tool, dict(args), status, [], payload, None, 0.0, unverified)  # type: ignore[arg-type]


def listing(traces: list[object], *, unverified: bool = False, **args: object) -> ToolResult:
    payload: GetFailingTracesResult = fx.failing_traces_result(traces)  # type: ignore[arg-type]
    status = "ok" if traces else "empty"
    return result(
        "get_failing_traces", payload, status=status, unverified=unverified and not traces, **args
    )


def judge_failures(n: int) -> list[object]:
    return [fx.failing_trace(f"jf-{i}", "judge_pipeline_failure") for i in range(n)]


def blocks(n: int, rail: str | None = "faithfulness") -> list[object]:
    return [fx.failing_trace(f"b{i}", "guardrail_blocked", block_rail=rail) for i in range(n)]


def errors(n: int, kind: str | None = "TimeoutError") -> list[object]:
    return [fx.failing_trace(f"e{i}", "rag_system_error", error_kind=kind) for i in range(n)]


# 1. An unverified empty never becomes negative evidence.

NEGATIVE_CAPABLE: list[tuple[Signal, str]] = [
    ("judge_failures", "judge_failed"),
    ("block_cluster", "blocked"),
    ("error_cluster", "error"),
]


@pytest.mark.parametrize("signal, failure_type", NEGATIVE_CAPABLE)
def test_a_verified_empty_listing_shows_the_signal_absent(
    signal: Signal, failure_type: str
) -> None:
    obs = evaluate(signal, None, [listing([], failure_type=failure_type)])
    assert obs.observed is False


@pytest.mark.parametrize("signal, failure_type", NEGATIVE_CAPABLE)
def test_an_unverified_empty_listing_cannot_tell(signal: Signal, failure_type: str) -> None:
    obs = evaluate(signal, None, [listing([], unverified=True, failure_type=failure_type)])
    assert obs.observed is None
    assert "failed query" in obs.detail


@pytest.mark.parametrize(
    "signal, make",
    [("judge_failures", judge_failures), ("block_cluster", blocks), ("error_cluster", errors)],
)
def test_data_bearing_results_are_unaffected_by_an_unverified_empty(
    signal: Signal, make: object
) -> None:
    data = listing(make(6))  # type: ignore[operator]
    unverified = listing([], unverified=True)
    assert evaluate(signal, None, [data]).observed is True
    assert evaluate(signal, None, [unverified, data]).observed is True


def test_a_listing_of_another_failure_type_says_nothing_about_judge_failures() -> None:
    """Two blocked requests were returned. That the listing held no judge failure shows
    nothing, because it was never asked for them."""
    only_blocked = listing(blocks(2), failure_type="blocked")
    assert evaluate("judge_failures", None, [only_blocked]).observed is None
    asked = listing(blocks(2), failure_type="any")
    assert evaluate("judge_failures", None, [asked]).observed is False


# 3. A prediction is bound to the subject it names.


def _flagged(chunks_flagged: list[str], *, n: int = 3) -> list[ToolResult]:
    return [
        result(
            "get_trace_detail",
            fx.trace_detail(
                f"d{i}",
                chunks=["C-1", "C-2"],
                flash_faithfulness=0.9,
                frontier_faithfulness=0.1,
                contradicting_chunks=chunks_flagged,
            ),
        )
        for i in range(n)
    ]


def test_a_named_chunk_that_the_traces_flag_is_supported() -> None:
    obs = evaluate("chunk_contradicted", "C-1", _flagged(["C-1"]))
    assert obs.observed is True and obs.subject == "C-1" and obs.support


def test_a_named_chunk_is_not_satisfied_by_a_different_flagged_chunk() -> None:
    obs = evaluate("chunk_contradicted", "C-2", _flagged(["C-1"]))
    assert obs.observed is not True
    assert obs.support == ()
    assert "C-2" in obs.detail


def test_a_chunk_prediction_that_cannot_be_checked_is_unknown() -> None:
    assert evaluate("chunk_contradicted", "C-1", _flagged(["C-1"], n=1)).observed is None


def test_an_unnamed_chunk_prediction_still_reads_every_retrieved_record() -> None:
    obs = evaluate("chunk_contradicted", None, _flagged(["C-1"]))
    assert obs.observed is True and obs.subject == "C-1"


def _failed_traces(chunk_lists: list[list[str]]) -> list[ToolResult]:
    return [
        result(
            "get_trace_detail",
            fx.trace_detail(f"f{i}", rag_status="blocked", chunks=chunks),
        )
        for i, chunks in enumerate(chunk_lists)
    ]


def test_a_named_shared_chunk_is_supported_when_all_failures_retrieved_it() -> None:
    obs = evaluate("chunk_shared_by_failures", "C-1", _failed_traces([["C-1", "C-2"], ["C-1"]]))
    assert obs.observed is True and obs.subject == "C-1"


def test_a_named_chunk_is_not_satisfied_by_a_different_shared_chunk() -> None:
    obs = evaluate("chunk_shared_by_failures", "C-9", _failed_traces([["C-1", "C-2"], ["C-1"]]))
    assert obs.observed is not True and obs.support == ()


def test_a_shared_chunk_prediction_with_one_failed_trace_is_unknown() -> None:
    assert evaluate("chunk_shared_by_failures", "C-1", _failed_traces([["C-1"]])).observed is None


def test_a_named_rail_is_supported_only_when_that_rail_dominates() -> None:
    data = [listing(blocks(6, "faithfulness"))]
    assert evaluate("block_cluster", "faithfulness", data).observed is True
    other = evaluate("block_cluster", "check prompt injection", data)
    assert other.observed is not True and other.support == ()


def test_a_named_rail_cannot_be_checked_when_the_traces_record_no_rail() -> None:
    data = [listing(blocks(6, None))]
    assert evaluate("block_cluster", "faithfulness", data).observed is None


def test_a_named_error_kind_is_supported_only_when_that_kind_dominates() -> None:
    data = [listing(errors(6, "TimeoutError"))]
    assert evaluate("error_cluster", "TimeoutError", data).observed is True
    other = evaluate("error_cluster", "KeyError", data)
    assert other.observed is not True and other.support == ()


def test_a_named_error_kind_cannot_be_checked_when_the_traces_record_no_kind() -> None:
    assert evaluate("error_cluster", "TimeoutError", [listing(errors(6, None))]).observed is None


def test_drift_for_another_judge_is_not_a_reading_of_the_named_judge() -> None:
    drifted = result("get_drift_report", fx.drift_report(state="drifted"))
    assert evaluate("judge_drift", "gemini-rubric", [drifted]).observed is True
    assert evaluate("judge_drift", "hhem", [drifted]).observed is None


# 4. Drift history is usable without a current reading.


def _transition(new_state: str, previous: str, at: str = "2026-10-01T10:00:00+00:00"):  # type: ignore[no-untyped-def]
    return TransitionRecordSummary(
        observed_at=at,
        previous_state=previous,
        new_state=new_state,
        previous_mode="normal",
        new_mode="normal",
        reason="kappa below the entry threshold",
        kappa=0.31,
    )


def test_a_transition_into_drift_is_reported_as_past_drift_not_a_present_reading() -> None:
    report = fx.drift_report(state=None, transitions=[_transition("drifted", "healthy")])
    obs = evaluate("judge_drift", None, [result("get_drift_report", report)])
    assert obs.observed is True
    assert obs.support and obs.support[0].kind == "drift_report"
    assert "no current health reading" in obs.detail
    assert "drifted" in obs.detail


def test_a_recovery_transition_is_hedged_and_not_a_current_healthy_reading() -> None:
    report = fx.drift_report(
        state=None,
        transitions=[
            _transition("drifted", "healthy", "2026-10-01T08:00:00+00:00"),
            _transition("healthy", "drifted", "2026-10-01T10:00:00+00:00"),
        ],
    )
    obs = evaluate("judge_drift", None, [result("get_drift_report", report)])
    assert obs.observed is False
    assert "no current health reading" in obs.detail
    assert obs.against


def test_a_current_reading_still_outranks_the_history() -> None:
    report = fx.drift_report(state="healthy", transitions=[_transition("drifted", "healthy")])
    obs = evaluate("judge_drift", None, [result("get_drift_report", report)])
    assert obs.observed is False and "no current health reading" not in obs.detail


def test_an_unrecognised_last_transition_state_is_unknown() -> None:
    report = fx.drift_report(state=None, transitions=[_transition("degraded", "healthy")])
    assert evaluate("judge_drift", None, [result("get_drift_report", report)]).observed is None


# 5. A finding cannot establish a diagnosis in a subsystem its records cannot bear on.


def _hypothesis(hid: str, subsystem: Subsystem, *predictions: PredictedObservation) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hid,
        statement=f"a fault in {subsystem}",
        subsystem=subsystem,
        symptom="s",
        predicted_observations=list(predictions),
    )


CHUNK_PREDICTION = PredictedObservation(
    tool="get_trace_detail",
    description="a chunk is contradicted",
    signal="chunk_contradicted",
    subject="C-1",
)


def test_a_chunk_observation_cannot_establish_an_output_rails_diagnosis() -> None:
    results = _flagged(["C-1"])
    assert evaluate("chunk_contradicted", "C-1", results).observed is True  # genuine citations
    ledger, assessments = assess([_hypothesis("h1", "output_rails", CHUNK_PREDICTION)], results)
    assert ledger[0].status != "supported"
    assert ledger[0].supporting == []
    assert assessments["h1"].rejected
    assert "output_rails" in assessments["h1"].rejected[0]
    outcome = review(ledger, assessments, can_continue=False, unverified_empties=False)
    assert outcome.decision == "abstain"
    assert any("output_rails" in line for line in outcome.unresolved)


def test_the_same_chunk_observation_does_establish_a_retrieval_diagnosis() -> None:
    ledger, _ = assess([_hypothesis("h1", "retrieval", CHUNK_PREDICTION)], _flagged(["C-1"]))
    assert ledger[0].status == "supported" and ledger[0].supporting


def test_a_signal_that_fits_two_subsystems_keeps_the_observation_and_declines_to_pick_one() -> None:
    """The chunk finding fits retrieval and the judges. Neither hypothesis is rejected, both
    keep the supported observation, and the review names neither."""
    results = _flagged(["C-1"])
    ledger, assessments = assess(
        [
            _hypothesis("h1", "retrieval", CHUNK_PREDICTION),
            _hypothesis("h2", "judges", CHUNK_PREDICTION),
        ],
        results,
    )
    assert [h.status for h in ledger] == ["supported", "supported"]
    assert all(h.supporting for h in ledger)
    outcome = review(ledger, assessments, can_continue=False, unverified_empties=False)
    assert outcome.decision == "abstain" and not outcome.leaders
    assert any("each supported" in line for line in outcome.unresolved)


def test_a_rail_block_cluster_does_not_establish_an_input_rails_diagnosis() -> None:
    prediction = PredictedObservation(
        tool="get_failing_traces",
        description="blocks cluster on a rail",
        signal="block_cluster",
        subject=None,
    )
    results = [listing(blocks(6, "faithfulness"))]
    ledger, assessments = assess([_hypothesis("h1", "input_rails", prediction)], results)
    assert ledger[0].status == "open" and assessments["h1"].rejected


def test_a_red_team_miss_of_an_output_rail_bears_on_output_rails_only() -> None:
    missed = fx.execution(
        "rt-1",
        "OUT-001",
        "output_schema",
        outcome="missed",
        expected_caught_by="schema-enforcement",
        target_layer="schema-enforcement",
    )
    obs = evaluate(
        "rail_regression",
        None,
        [result("get_red_team_execution", RedTeamExecutionResult(found=True, execution=missed))],
    )
    assert obs.observed is True and obs.subsystems == frozenset({"output_rails"})


def test_every_rail_name_the_platform_defines_is_classified() -> None:
    from finsentry.investigator.signals import RAIL_STAGE

    assert set(get_args(Rail)) <= set(RAIL_STAGE)
