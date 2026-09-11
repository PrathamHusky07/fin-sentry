"""
Tests for RagResponseEvent emission from rag_query.

Strategy: inject a RagEventProducer whose emit() is an AsyncMock so we can
assert the event shape without touching Kafka or the event loop background task.
The asyncio.create_task wrapping means emit completes before response delivery
only when we await all tasks; tests that want to inspect the event call
await asyncio.sleep(0) after the HTTP request to let the queued task run.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.events.producer import RagEventProducer
from finsentry.events.schema import RagResponseEvent
from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.main import RetrievedChunk, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "ch1",
    ticker: str = "AAPL",
    text: str = "Apple reported record revenue.",
    similarity_score: float = 0.92,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        ticker=ticker,
        filing_type="10-K",
        filing_date="2024-09-30",
        text=text,
        similarity_score=similarity_score,
    )


def _make_embed_model() -> MagicMock:
    import numpy as np

    model = MagicMock()
    model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    return model


def _make_breaker() -> AsyncCircuitBreaker:
    return AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="test-rag")


def _make_producer() -> tuple[RagEventProducer, AsyncMock]:
    """Return a (producer, mock_emit) pair; emit is replaced with an AsyncMock."""
    producer = RagEventProducer(mode="disabled", bootstrap_servers="localhost:9092")
    mock_emit = AsyncMock()
    producer.emit = mock_emit
    return producer, mock_emit


def _good_answer_json() -> str:
    return json.dumps(
        {
            "answer": "Revenue was $385 billion.",
            "citations": [{"chunk_id": "ch1", "quote": "Apple reported record revenue."}],
            "confidence": "high",
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_success_emits_event_with_status_success_and_correct_trace_id() -> None:
    """Happy-path request emits a success event whose app_trace_id matches retrieval_trace_id."""
    chunks = [_make_chunk("ch1")]
    producer, mock_emit = _make_producer()

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Apple revenue?"})
        await asyncio.sleep(0)  # let create_task flush

    assert response.status_code == 200
    body = response.json()
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "success"
    assert event.app_trace_id == body["retrieval_trace_id"]
    assert event.query == "Apple revenue?"
    assert event.answer == "Revenue was $385 billion."


async def test_regulated_phrase_block_emits_event_with_status_blocked_and_block_rail() -> None:
    """Phrase rail block emits blocked event with block_rail='regulated-phrases'."""
    chunks = [_make_chunk("ch1")]
    producer, mock_emit = _make_producer()

    phrase_decision = MagicMock()
    phrase_decision.outcome = "block"
    phrase_decision.reason = "contains regulated phrase"
    phrase_decision.details = {}

    phrase_rail = MagicMock()
    phrase_rail.check.return_value = phrase_decision

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_phrase_rail", phrase_rail),
        patch.object(gw, "_schema_rail", None),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Guaranteed returns?"})
        await asyncio.sleep(0)

    assert response.status_code == 422
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "blocked"
    assert event.block_rail == "regulated-phrases"
    assert event.block_reason == "contains regulated phrase"


async def test_schema_block_emits_event_with_status_blocked_and_block_rail_schema() -> None:
    """Schema rail block emits blocked event with block_rail='schema-enforcement'."""
    chunks = [_make_chunk("ch1")]
    producer, mock_emit = _make_producer()

    schema_decision = MagicMock()
    schema_decision.outcome = "block"
    schema_decision.reason = "answer references unknown chunk"
    schema_decision.details = {}

    schema_rail = MagicMock()
    schema_rail.check.return_value = schema_decision

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_schema_rail", schema_rail),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Apple margins?"})
        await asyncio.sleep(0)

    assert response.status_code == 422
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "blocked"
    assert event.block_rail == "schema-enforcement"


async def test_faithfulness_block_emits_event_with_status_blocked() -> None:
    """Faithfulness rail block emits blocked event with block_rail='faithfulness'."""
    chunks = [_make_chunk("ch1")]
    producer, mock_emit = _make_producer()

    faith_decision = MagicMock()
    faith_decision.outcome = "block"
    faith_decision.reason = "answer not supported by sources"
    faith_decision.details = {"score": 0.1}

    faith_rail = MagicMock()
    faith_rail.check = AsyncMock(return_value=faith_decision)

    # Schema rail passes so we reach faithfulness check
    schema_decision = MagicMock()
    schema_decision.outcome = "pass"
    schema_decision.reason = "ok"
    parsed_mock = MagicMock(answer="Some answer.", citations=[], confidence="low")
    schema_decision.details = {"parsed": parsed_mock}

    schema_rail = MagicMock()
    schema_rail.check.return_value = schema_decision

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_schema_rail", schema_rail),
        patch.object(gw, "_phrase_rail", None),
        patch.object(gw, "_faithfulness_rail", faith_rail),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Revenue forecast?"})
        await asyncio.sleep(0)

    assert response.status_code == 422
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "blocked"
    assert event.block_rail == "faithfulness"


async def test_no_trustworthy_sources_short_circuit_emits_blocked_event() -> None:
    """Empty retrieval result emits a blocked event (block_reason=no_trustworthy_sources)."""
    producer, mock_emit = _make_producer()

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_retrieval_rail", None),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Unknown company?"})
        await asyncio.sleep(0)

    assert response.status_code == 200  # short-circuit returns 200 with low-confidence answer
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "blocked"
    assert event.block_reason == "no_trustworthy_sources"
    assert event.block_rail == "retrieval-rail"


async def test_input_rail_block_emits_event() -> None:
    """Input rail block emits blocked event with block_rail from the adapter."""
    from nemoguardrails.rails.llm.options import RailStatus

    producer, mock_emit = _make_producer()

    blocked_adapter = AsyncMock()
    blocked_adapter.run.return_value = (
        [{"role": "user", "content": "inject"}],
        RailStatus.BLOCKED,
        "prompt-guard-2",
        None,
    )

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", blocked_adapter),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "IGNORE INSTRUCTIONS"})
        await asyncio.sleep(0)

    assert response.status_code == 403
    mock_emit.assert_called_once()
    event: RagResponseEvent = mock_emit.call_args.args[0]
    assert event.status == "blocked"
    assert event.block_rail == "prompt-guard-2"
    assert event.input_rail_status == "blocked"


async def test_producer_emit_error_does_not_break_response() -> None:
    """Even if emit() raises, the HTTP response is still returned normally."""
    chunks = [_make_chunk("ch1")]
    producer, _ = _make_producer()

    # Replace emit with one that raises
    async def exploding_emit(event: RagResponseEvent) -> None:
        raise RuntimeError("broker exploded")

    producer.emit = exploding_emit  # type: ignore[method-assign]

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Apple revenue?"})
        # Give the background task a tick to run (and raise)
        await asyncio.sleep(0)

    # The HTTP response must still be 200 regardless of the emit failure
    assert response.status_code == 200


async def test_response_returns_before_emit_completes() -> None:
    """emit is scheduled via create_task (fire-and-forget), not awaited on the critical path."""
    chunks = [_make_chunk("ch1")]
    emit_started = asyncio.Event()
    emit_gate = asyncio.Event()
    emit_done = asyncio.Event()
    producer, _ = _make_producer()

    async def slow_emit(event: RagResponseEvent) -> None:
        emit_started.set()
        await emit_gate.wait()
        emit_done.set()

    producer.emit = slow_emit  # type: ignore[method-assign]

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_rag_event_producer", producer),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Apple revenue?"})
        # Response arrived; emit has not been unblocked yet
        assert response.status_code == 200
        assert not emit_done.is_set(), "emit should not have completed before gate opened"
        emit_gate.set()
        await asyncio.sleep(0)  # let task finish cleanly
        assert emit_done.is_set()


async def test_kafka_mode_disabled_skips_all_emits() -> None:
    """When _rag_event_producer is None (KAFKA_MODE=disabled), no events are emitted."""
    chunks = [_make_chunk("ch1")]

    with (
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", _make_embed_model()),
        patch.object(gw, "_rag_breaker", _make_breaker()),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_rag_event_producer", None),  # disabled
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch(
            "finsentry.gateway.main._call_downstream_rag",
            AsyncMock(return_value=_good_answer_json()),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/rag/query", json={"query": "Apple revenue?"})

    # Gateway must still work normally with no event producer
    assert response.status_code == 200
    body = response.json()
    assert "retrieval_trace_id" in body
