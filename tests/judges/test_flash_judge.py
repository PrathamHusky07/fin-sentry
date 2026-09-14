"""Tests for finsentry.judges.flash_judge.FlashJudge and JudgeVerdictProducer."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from finsentry.events.schema import JudgeVerdictEvent, RagResponseEvent
from finsentry.judges.flash_judge import FlashJudge, JudgeVerdictProducer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(**overrides: Any) -> RagResponseEvent:
    defaults: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "app_trace_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "success",
        "endpoint": "/v1/rag/query",
        "query": "What was Apple Q1 2024 revenue?",
        "ticker": "AAPL",
        "answer": "Apple Q1 2024 revenue was $119.6B.",
        "retrieved_chunks_text": ["Apple had $119.6B revenue in Q1 2024."],
        "total_latency_ms": 200,
    }
    defaults.update(overrides)
    return RagResponseEvent.model_validate(defaults)


def _mock_generate_fn(responses: list[tuple[str, int, int, int]]) -> Any:
    call_iter = iter(responses)

    async def _gen(prompt: str) -> tuple[str, int, int, int]:
        return next(call_iter)

    return _gen


# ---------------------------------------------------------------------------
# FlashJudge tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_flash_judge_disabled_returns_skipped_no_key() -> None:
    """mode=disabled skips all metrics with skipped_no_key."""
    judge = FlashJudge(mode="disabled")
    event = _make_event()
    verdict = await judge.evaluate(event)

    assert isinstance(verdict, JudgeVerdictEvent)
    assert verdict.faithfulness_status == "skipped_no_key"
    assert verdict.answer_relevance_status == "skipped_no_key"
    assert verdict.context_relevance_status == "skipped_no_key"
    assert verdict.faithfulness_score is None
    assert verdict.source_event_id == event.event_id
    assert verdict.app_trace_id == event.app_trace_id
    # New metadata fields
    assert verdict.judge_tier == "flash"
    assert verdict.judge_model == judge._model_name
    assert verdict.status == "failed"  # 0 of 3 metrics completed
    assert verdict.evaluation_latency_ms >= 0
    assert verdict.total_cost_usd == 0.0


@pytest.mark.anyio
async def test_flash_judge_non_success_event_returns_skipped_non_success() -> None:
    """Blocked or error events are not scored (no answer to evaluate)."""
    judge = FlashJudge(mode="disabled")
    event = _make_event(status="blocked", answer="", block_reason="safety")
    verdict = await judge.evaluate(event)

    assert verdict.faithfulness_status == "skipped_no_key"


@pytest.mark.anyio
async def test_flash_judge_with_mock_generate_fn_scores_all_three_metrics() -> None:
    """When generate_fn is injectable, all three metrics complete successfully."""
    judge = FlashJudge(mode="disabled")

    # Patch _make_generate_fn to return a mock that always returns valid responses
    claims_json = json.dumps(["Apple revenue was high."])
    verdict_yes = json.dumps({"verdict": "yes", "rationale": "confirmed"})
    ar_json = json.dumps({"score": 0.9, "rationale": "Directly answers."})
    cr_json = json.dumps({"score": 0.8, "rationale": "Relevant chunk."})

    call_count = 0

    async def _fake_gen(prompt: str) -> tuple[str, int, int, int]:
        nonlocal call_count
        call_count += 1
        # faithfulness: call 1 = extraction, call 2 = verification
        # answer_relevance: call 3
        # context_relevance: call 4
        if call_count == 1:
            return claims_json, 100, 30, 0
        if call_count == 2:
            return verdict_yes, 50, 20, 0
        if call_count == 3:
            return ar_json, 80, 25, 0
        return cr_json, 80, 25, 0

    judge._client = MagicMock()  # not None so non-disabled path runs
    judge._make_generate_fn = lambda: _fake_gen  # type: ignore[method-assign]

    event = _make_event()
    verdict = await judge.evaluate(event)

    assert verdict.faithfulness_status == "complete"
    assert verdict.faithfulness_score == 1.0
    assert verdict.answer_relevance_status == "complete"
    assert verdict.answer_relevance_score == 0.9
    assert verdict.context_relevance_status == "complete"
    assert verdict.context_relevance_score == 0.8
    assert verdict.total_gemini_calls == 4
    # New metadata fields
    assert verdict.judge_tier == "flash"
    assert verdict.judge_model == judge._model_name
    assert verdict.status == "complete"  # all 3 metrics returned a score
    assert verdict.evaluation_latency_ms >= 0
    assert verdict.total_cost_usd >= 0.0


@pytest.mark.anyio
async def test_flash_judge_verdict_links_to_source_event() -> None:
    """Verdict carries source_event_id and app_trace_id from the source event."""
    judge = FlashJudge(mode="disabled")
    event = _make_event()
    verdict = await judge.evaluate(event)

    assert verdict.source_event_id == event.event_id
    assert verdict.app_trace_id == event.app_trace_id


@pytest.mark.anyio
async def test_flash_judge_verdict_has_unique_event_id() -> None:
    """Each verdict gets a distinct UUID event_id."""
    judge = FlashJudge(mode="disabled")
    v1 = await judge.evaluate(_make_event())
    v2 = await judge.evaluate(_make_event())
    assert v1.event_id != v2.event_id


# ---------------------------------------------------------------------------
# JudgeVerdictProducer tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_judge_verdict_producer_emit_calls_send_and_wait() -> None:
    """emit() calls send_and_wait with the serialized verdict."""
    fake_kafka = AsyncMock()
    fake_kafka.start = AsyncMock()
    fake_kafka.stop = AsyncMock()
    fake_kafka.send_and_wait = AsyncMock()

    producer = JudgeVerdictProducer(
        bootstrap_servers="localhost:19092",
        topic="judge-verdicts",
    )
    producer.inject_producer(fake_kafka)
    await producer.start()

    judge = FlashJudge(mode="disabled")
    verdict = await judge.evaluate(_make_event())
    await producer.emit(verdict)

    fake_kafka.send_and_wait.assert_called_once()
    call_kwargs = fake_kafka.send_and_wait.call_args
    assert call_kwargs[0][0] == "judge-verdicts"  # topic
    payload = json.loads(call_kwargs[1]["value"])
    assert payload["app_trace_id"] == verdict.app_trace_id


@pytest.mark.anyio
async def test_judge_verdict_producer_emit_without_start_logs_warning() -> None:
    """emit() without start() logs a warning instead of raising."""
    producer = JudgeVerdictProducer("localhost:19092", "judge-verdicts")
    judge = FlashJudge(mode="disabled")
    verdict = await judge.evaluate(_make_event())
    # Should not raise
    await producer.emit(verdict)


@pytest.mark.anyio
async def test_judge_verdict_event_serializes_to_json() -> None:
    """JudgeVerdictEvent.to_kafka_json() produces valid UTF-8 JSON."""
    judge = FlashJudge(mode="disabled")
    verdict = await judge.evaluate(_make_event())
    payload = verdict.to_kafka_json()
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["schema_version"] == "1.0"
    assert decoded["app_trace_id"] == verdict.app_trace_id
