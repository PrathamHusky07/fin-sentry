from __future__ import annotations

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
