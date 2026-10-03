from __future__ import annotations

import math

import pytest

from finsentry.frontier.types import (
    Citation,
    FrontierEvaluationInput,
    FrontierVerdictEvent,
    JudgeHealth,
    JudgeResult,
)


def _sample_judge_result(judge_id: str = "hhem-2.1-open", score: float = 0.9) -> JudgeResult:
    return JudgeResult(
        judge_id=judge_id,
        judge_family="hhem",
        methodology="nli_premise_hypothesis",
        status="success",
        faithfulness_score=score,
        evidence={"raw_score": score},
        latency_ms=120,
    )


def _sample_verdict_event() -> FrontierVerdictEvent:
    return FrontierVerdictEvent(
        app_trace_id="trace-1",
        verdict="frontier_pass",
        per_judge_results=[_sample_judge_result()],
        score_delta=None,
        disagreement_classification="insufficient_judges",
        evaluation_ts="2026-10-02T00:00:00+00:00",
        frontier_sampling_decision_key="trace-1",
    )


def test_frontier_verdict_event_round_trips_through_kafka_json() -> None:
    original = _sample_verdict_event()
    payload = original.to_kafka_json()
    restored = FrontierVerdictEvent.from_kafka_json(payload)

    assert restored == original


def test_frontier_verdict_event_round_trip_preserves_multiple_judge_results() -> None:
    original = FrontierVerdictEvent(
        app_trace_id="trace-2",
        verdict="disagreement_review_needed",
        per_judge_results=[
            _sample_judge_result("hhem-2.1-open", 0.9),
            _sample_judge_result("gemini-rubric", 0.4),
        ],
        score_delta=0.5,
        disagreement_classification="strong_disagreement",
        evaluation_ts="2026-10-02T00:01:00+00:00",
        frontier_sampling_decision_key="trace-2",
    )
    restored = FrontierVerdictEvent.from_kafka_json(original.to_kafka_json())

    assert restored == original
    assert len(restored.per_judge_results) == 2


def test_frontier_verdict_event_rejects_invalid_verdict_literal() -> None:
    with pytest.raises(ValueError, match="verdict"):
        FrontierVerdictEvent(
            app_trace_id="trace-3",
            verdict="not_a_real_verdict",  # type: ignore[arg-type]
            per_judge_results=[],
            score_delta=None,
            disagreement_classification="insufficient_judges",
            evaluation_ts="2026-10-02T00:00:00+00:00",
            frontier_sampling_decision_key="trace-3",
        )


def test_frontier_verdict_event_rejects_invalid_disagreement_classification() -> None:
    with pytest.raises(ValueError, match="disagreement_classification"):
        FrontierVerdictEvent(
            app_trace_id="trace-4",
            verdict="frontier_pass",
            per_judge_results=[],
            score_delta=None,
            disagreement_classification="total_chaos",  # type: ignore[arg-type]
            evaluation_ts="2026-10-02T00:00:00+00:00",
            frontier_sampling_decision_key="trace-4",
        )


def test_judge_result_rejects_invalid_status_literal() -> None:
    with pytest.raises(ValueError, match="status"):
        JudgeResult(
            judge_id="hhem-2.1-open",
            judge_family="hhem",
            methodology="nli_premise_hypothesis",
            status="not_a_real_status",  # type: ignore[arg-type]
        )


def test_judge_health_rejects_invalid_status_literal() -> None:
    with pytest.raises(ValueError, match="status"):
        JudgeHealth(
            judge_id="hhem-2.1-open",
            status="on_fire",  # type: ignore[arg-type]
            last_success_ts=None,
            error_rate_1h=0.0,
        )


def test_judge_health_accepts_valid_status() -> None:
    health = JudgeHealth(
        judge_id="hhem-2.1-open", status="healthy", last_success_ts=None, error_rate_1h=0.0
    )
    assert health.status == "healthy"


def test_judge_result_rejects_score_above_one_on_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(
            judge_id="j",
            judge_family="f",
            methodology="m",
            status="success",
            faithfulness_score=1.1,
        )


def test_judge_result_rejects_score_below_zero_on_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(
            judge_id="j", judge_family="f", methodology="m", status="success",
            faithfulness_score=-0.01,
        )


def test_judge_result_rejects_nan_score_on_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(
            judge_id="j", judge_family="f", methodology="m", status="success",
            faithfulness_score=math.nan,
        )


def test_judge_result_rejects_infinite_score_on_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(
            judge_id="j", judge_family="f", methodology="m", status="success",
            faithfulness_score=math.inf,
        )


def test_judge_result_rejects_missing_score_on_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(judge_id="j", judge_family="f", methodology="m", status="success")


def test_judge_result_rejects_score_present_on_non_success() -> None:
    with pytest.raises(ValueError, match="faithfulness_score"):
        JudgeResult(
            judge_id="j", judge_family="f", methodology="m", status="timeout",
            faithfulness_score=0.5,
        )


def test_judge_result_accepts_boundary_scores_zero_and_one() -> None:
    low = JudgeResult(
        judge_id="j", judge_family="f", methodology="m", status="success",
        faithfulness_score=0.0,
    )
    high = JudgeResult(
        judge_id="j", judge_family="f", methodology="m", status="success",
        faithfulness_score=1.0,
    )
    assert low.faithfulness_score == 0.0
    assert high.faithfulness_score == 1.0


def test_judge_health_rejects_error_rate_above_one() -> None:
    with pytest.raises(ValueError, match="error_rate_1h"):
        JudgeHealth(judge_id="j", status="healthy", last_success_ts=None, error_rate_1h=1.5)


def test_judge_health_rejects_negative_error_rate() -> None:
    with pytest.raises(ValueError, match="error_rate_1h"):
        JudgeHealth(judge_id="j", status="healthy", last_success_ts=None, error_rate_1h=-0.1)


def test_frontier_verdict_event_rejects_score_delta_out_of_range() -> None:
    with pytest.raises(ValueError, match="score_delta"):
        FrontierVerdictEvent(
            app_trace_id="trace-6",
            verdict="frontier_pass",
            per_judge_results=[],
            score_delta=1.2,
            disagreement_classification="agreement",
            evaluation_ts="2026-10-02T00:00:00+00:00",
            frontier_sampling_decision_key="trace-6",
        )


def test_frontier_verdict_event_accepts_none_score_delta() -> None:
    event = FrontierVerdictEvent(
        app_trace_id="trace-7",
        verdict="frontier_unavailable",
        per_judge_results=[],
        score_delta=None,
        disagreement_classification="insufficient_judges",
        evaluation_ts="2026-10-02T00:00:00+00:00",
        frontier_sampling_decision_key="trace-7",
    )
    assert event.score_delta is None


def test_frontier_evaluation_input_carries_citations() -> None:
    evaluation_input = FrontierEvaluationInput(
        app_trace_id="trace-5",
        question="What was Apple's total net sales in fiscal year 2024?",
        answer="Apple's total net sales in fiscal year 2024 were $391,035 million.",
        citations=[
            Citation(
                chunk_id="fecfcfbf665bb339",
                quote="Total net sales | $391,035",
                retrieved_text="Net sales disaggregated by significant products...",
            )
        ],
        retrieved_context_chunks=["Net sales disaggregated by significant products..."],
        original_rag_event_ts="2026-10-02T00:00:00+00:00",
    )
    assert evaluation_input.citations[0].chunk_id == "fecfcfbf665bb339"
