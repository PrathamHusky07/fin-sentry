from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from finsentry.frontier.adapters.hhem_adapter import HHEMAdapter
from finsentry.frontier.types import Citation, FrontierEvaluationInput


def _evaluation_input() -> FrontierEvaluationInput:
    return FrontierEvaluationInput(
        app_trace_id="trace-1",
        question="What was Apple's total net sales in fiscal year 2024?",
        answer="Apple's total net sales in fiscal year 2024 were $391,035 million.",
        citations=[Citation(chunk_id="c1", quote="391,035", retrieved_text="context text")],
        retrieved_context_chunks=["Total net sales were $391,035 million in fiscal 2024."],
        original_rag_event_ts="2026-10-02T00:00:00+00:00",
    )


def _adapter_with_mock_model(predict_return: object) -> HHEMAdapter:
    """Build an HHEMAdapter whose _load() succeeds with a mock model."""
    mock_model = MagicMock()
    mock_model.predict.return_value = predict_return
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=mock_model,
    ):
        adapter = HHEMAdapter()
    assert adapter.is_available
    return adapter


def test_successful_evaluation_returns_score_in_unit_interval() -> None:
    adapter = _adapter_with_mock_model([0.87])

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "success"
    assert result.faithfulness_score is not None
    assert 0.0 <= result.faithfulness_score <= 1.0
    assert result.judge_id == "hhem-2.1-open"
    assert result.judge_family == "hhem"
    assert result.methodology == "nli_premise_hypothesis"


def test_model_load_failure_returns_unavailable_not_raise() -> None:
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        side_effect=AttributeError("'HHEMv2ForSequenceClassification' object has no attribute 'x'"),
    ):
        adapter = HHEMAdapter()

    assert not adapter.is_available

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "unavailable"
    assert result.error_detail is not None
    assert result.faithfulness_score is None


def test_timeout_returns_timeout_status() -> None:
    def _slow_predict(_pairs: object) -> list[float]:
        import time

        time.sleep(0.2)
        return [0.5]

    mock_model = MagicMock()
    mock_model.predict.side_effect = _slow_predict
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=mock_model,
    ):
        adapter = HHEMAdapter(timeout_s=0.01)

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "timeout"


def test_runtime_exception_during_evaluate_returns_model_error() -> None:
    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("tensor shape mismatch")
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=mock_model,
    ):
        adapter = HHEMAdapter()

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "model_error"
    assert "tensor shape mismatch" in (result.error_detail or "")


def test_health_check_healthy_when_liveness_pair_succeeds() -> None:
    adapter = _adapter_with_mock_model([0.95])

    health = asyncio.run(adapter.health_check())

    assert health.status == "healthy"
    assert health.judge_id == "hhem-2.1-open"


def test_health_check_degraded_when_liveness_pair_fails() -> None:
    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("boom")
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=mock_model,
    ):
        adapter = HHEMAdapter()

    health = asyncio.run(adapter.health_check())

    assert health.status == "degraded"


def test_health_check_unavailable_when_model_never_loaded() -> None:
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        side_effect=AttributeError("load failed"),
    ):
        adapter = HHEMAdapter()

    health = asyncio.run(adapter.health_check())

    assert health.status == "unavailable"
    assert health.error_rate_1h == 1.0
