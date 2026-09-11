"""
Tests for Milestone 0a/0b: rag.query.total root span wrapping all child spans,
and error event emission on exception paths.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import finsentry.gateway.main as gw
from finsentry.events.producer import RagEventProducer
from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.main import RetrievedChunk, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str = "ch1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        ticker="AAPL",
        filing_type="10-K",
        filing_date="2024-09-30",
        text="Apple reported record revenue.",
        similarity_score=0.92,
    )


def _make_embed_model() -> MagicMock:
    import numpy as np

    model = MagicMock()
    model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    return model


def _make_breaker() -> AsyncCircuitBreaker:
    return AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="test-root")


def _make_producer() -> tuple[RagEventProducer, AsyncMock]:
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


def _base_patches(producer: RagEventProducer) -> dict[str, object]:
    return {
        "finsentry.gateway.main._DOWNSTREAM_URL": "http://fake-downstream",
        "finsentry.gateway.main._DATABASE_URL": "postgresql://fake",
        "finsentry.gateway.main._embed_model": _make_embed_model(),
        "finsentry.gateway.main._rag_breaker": _make_breaker(),
        "finsentry.gateway.main._retrieval_rail": None,
        "finsentry.gateway.main._schema_rail": None,
        "finsentry.gateway.main._phrase_rail": None,
        "finsentry.gateway.main._faithfulness_rail": None,
        "finsentry.gateway.main._rag_event_producer": producer,
        "finsentry.gateway.main._adapter": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rag_query_total_root_span_wraps_child_spans() -> None:
    """rag.query.total root span exists and app_trace_id attribute equals retrieval_trace_id."""
    import opentelemetry.trace as otel_trace

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    gw._tracer = provider.get_tracer("finsentry.gateway")

    producer, mock_emit = _make_producer()

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "finsentry.gateway.main._fetch_chunks",
                new=AsyncMock(return_value=[_make_chunk()]),
            )
        )
        stack.enter_context(
            patch(
                "finsentry.gateway.main._call_downstream_rag",
                new=AsyncMock(return_value=_good_answer_json()),
            )
        )
        for k, v in _base_patches(producer).items():
            stack.enter_context(patch(k, v))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/rag/query",
                json={"query": "What is Apple revenue?", "ticker": "AAPL"},
            )

    assert resp.status_code == 200
    body = resp.json()
    retrieval_trace_id = body["retrieval_trace_id"]

    await asyncio.sleep(0)

    finished = exporter.get_finished_spans()
    span_names = {s.name for s in finished}
    assert "rag.query.total" in span_names, f"Spans: {span_names}"

    root = next(s for s in finished if s.name == "rag.query.total")
    assert root.attributes is not None
    assert root.attributes.get("app_trace_id") == retrieval_trace_id


@pytest.mark.anyio
async def test_error_path_emits_error_event_with_error_kind() -> None:
    """Unhandled exception in the handler emits status='error' with error_kind=type(exc).__name__.

    The embed step has no try/except, so an exception there propagates to the outer
    rag.query.total handler which fires 0b error emission logic.
    """

    producer, mock_emit = _make_producer()

    # Build an embed model whose encode() raises — this path has no internal try/except.
    bad_model = MagicMock()
    bad_model.encode.side_effect = RuntimeError("test failure")

    patches = {
        "finsentry.gateway.main._DOWNSTREAM_URL": "http://fake-downstream",
        "finsentry.gateway.main._DATABASE_URL": "postgresql://fake",
        "finsentry.gateway.main._embed_model": bad_model,
        "finsentry.gateway.main._rag_breaker": _make_breaker(),
        "finsentry.gateway.main._retrieval_rail": None,
        "finsentry.gateway.main._schema_rail": None,
        "finsentry.gateway.main._phrase_rail": None,
        "finsentry.gateway.main._faithfulness_rail": None,
        "finsentry.gateway.main._rag_event_producer": producer,
        "finsentry.gateway.main._adapter": None,
    }

    with ExitStack() as stack:
        for k, v in patches.items():
            stack.enter_context(patch(k, v))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/rag/query",
                json={"query": "What is Apple revenue?", "ticker": "AAPL"},
            )

    assert resp.status_code == 500

    await asyncio.sleep(0)

    assert mock_emit.called
    event = mock_emit.call_args[0][0]
    assert event.status == "error"
    assert event.error_kind == "RuntimeError"
    assert event.error_detail == "test failure"


@pytest.mark.anyio
async def test_vector_search_failure_emits_error_event() -> None:
    """Vector search exception emits status='error' with error_kind='vector_search_failed'."""
    producer, mock_emit = _make_producer()

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "finsentry.gateway.main._fetch_chunks",
                new=AsyncMock(side_effect=ConnectionError("db down")),
            )
        )
        for k, v in _base_patches(producer).items():
            stack.enter_context(patch(k, v))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/rag/query",
                json={"query": "What is Apple revenue?", "ticker": "AAPL"},
            )

    assert resp.status_code == 503

    await asyncio.sleep(0)

    assert mock_emit.called
    event = mock_emit.call_args[0][0]
    assert event.status == "error"
    assert event.error_kind == "vector_search_failed"


@pytest.mark.anyio
async def test_error_detail_truncated_to_500_chars() -> None:
    """error_detail is capped at 500 chars for errors reaching the outer handler."""
    producer, mock_emit = _make_producer()
    long_message = "X" * 1000

    # Use the embed path (no internal try/except) to trigger the outer handler.
    bad_model = MagicMock()
    bad_model.encode.side_effect = RuntimeError(long_message)

    patches = {
        "finsentry.gateway.main._DOWNSTREAM_URL": "http://fake-downstream",
        "finsentry.gateway.main._DATABASE_URL": "postgresql://fake",
        "finsentry.gateway.main._embed_model": bad_model,
        "finsentry.gateway.main._rag_breaker": _make_breaker(),
        "finsentry.gateway.main._retrieval_rail": None,
        "finsentry.gateway.main._schema_rail": None,
        "finsentry.gateway.main._phrase_rail": None,
        "finsentry.gateway.main._faithfulness_rail": None,
        "finsentry.gateway.main._rag_event_producer": producer,
        "finsentry.gateway.main._adapter": None,
    }

    with ExitStack() as stack:
        for k, v in patches.items():
            stack.enter_context(patch(k, v))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/rag/query",
                json={"query": "What is Apple revenue?"},
            )

    assert resp.status_code == 500

    await asyncio.sleep(0)

    assert mock_emit.called
    event = mock_emit.call_args[0][0]
    assert event.status == "error"
    assert len(event.error_detail) <= 500
