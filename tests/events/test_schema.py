"""Tests for RagResponseEvent schema: serialization, validation, and lifecycle fields."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from finsentry.events.schema import RagResponseEvent


def _success_event(**overrides: object) -> RagResponseEvent:
    defaults: dict[str, object] = {
        "event_id": "evt-uuid-1234",
        "app_trace_id": "req-uuid-5678",
        "timestamp_utc": "2026-09-11T12:00:00+00:00",
        "status": "success",
        "endpoint": "/v1/rag/query",
        "query": "What was Apple revenue?",
        "ticker": "AAPL",
        "retrieved_chunk_ids": ["c1", "c2"],
        "retrieved_chunks_text": ["Apple revenue was $391B.", "iPhone sales: $201B."],
        "answer": "Apple revenue was $391B in FY2024.",
        "citations": [{"chunk_id": "c1", "quote": "Apple revenue was $391B."}],
        "confidence": "high",
        "model_used": "llama3.1:8b",
        "input_rail_status": "pass",
        "output_rail_trace_snapshot": {"faithfulness": {"score": 1.0}},
        "total_latency_ms": 1500,
    }
    defaults.update(overrides)
    return RagResponseEvent(**defaults)  # type: ignore[arg-type]


def test_success_event_round_trip_serialization() -> None:
    """A success event serializes to bytes and deserializes back to an equal object."""
    event = _success_event()
    payload = event.to_kafka_json()
    assert isinstance(payload, bytes)
    restored = RagResponseEvent.from_kafka_json(payload)
    assert restored == event
    assert restored.schema_version == "1.0"
    assert restored.status == "success"
    assert restored.answer == "Apple revenue was $391B in FY2024."
    assert restored.confidence == "high"


def test_blocked_event_round_trip_with_null_generation_fields() -> None:
    """A blocked event round-trips; generation fields default to empty/None."""
    event = RagResponseEvent(
        event_id="evt-block-1",
        app_trace_id="req-block-1",
        timestamp_utc="2026-09-11T12:01:00+00:00",
        status="blocked",
        endpoint="/v1/rag/query",
        query="Guarantee returns on AAPL?",
        ticker="AAPL",
        retrieved_chunk_ids=["c1"],
        retrieved_chunks_text=["Apple filing text."],
        block_reason="guaranteed_returns",
        block_rail="regulated-phrases",
        input_rail_status="pass",
        total_latency_ms=200,
    )
    payload = event.to_kafka_json()
    restored = RagResponseEvent.from_kafka_json(payload)
    assert restored.status == "blocked"
    assert restored.block_rail == "regulated-phrases"
    assert restored.block_reason == "guaranteed_returns"
    # Generation fields default to empty
    assert restored.answer == ""
    assert restored.citations == []
    assert restored.confidence is None
    assert restored.error_kind is None


def test_error_event_round_trip_with_error_kind() -> None:
    """An error event carries error_kind and error_detail; generation fields absent."""
    event = RagResponseEvent(
        event_id="evt-err-1",
        app_trace_id="req-err-1",
        timestamp_utc="2026-09-11T12:02:00+00:00",
        status="error",
        endpoint="/v1/rag/query",
        query="Revenue?",
        ticker=None,
        error_kind="RuntimeError",
        error_detail="Connection refused",
        total_latency_ms=50,
    )
    payload = event.to_kafka_json()
    restored = RagResponseEvent.from_kafka_json(payload)
    assert restored.status == "error"
    assert restored.error_kind == "RuntimeError"
    assert restored.error_detail == "Connection refused"
    assert restored.ticker is None
    assert restored.answer == ""


def test_schema_version_defaults_to_1_0() -> None:
    """schema_version is always '1.0' when not supplied."""
    event = _success_event()
    assert event.schema_version == "1.0"
    payload = event.to_kafka_json()
    restored = RagResponseEvent.from_kafka_json(payload)
    assert restored.schema_version == "1.0"


def test_invalid_status_rejected() -> None:
    """A status value outside the Literal enum is rejected by Pydantic."""
    with pytest.raises(ValidationError):
        _success_event(status="pending")  # type: ignore[call-arg]


def test_invalid_confidence_rejected_when_present() -> None:
    """confidence must be 'low', 'medium', or 'high' if provided."""
    with pytest.raises(ValidationError):
        _success_event(confidence="very_high")  # type: ignore[call-arg]


def test_from_kafka_json_rejects_malformed_json() -> None:
    """from_kafka_json raises an error on malformed JSON bytes."""
    with pytest.raises(Exception):  # json.JSONDecodeError or pydantic ValidationError
        RagResponseEvent.from_kafka_json(b"not-json{{{")
