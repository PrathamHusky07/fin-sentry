"""Tests for RagEventProducer: disabled mode, kafka mode, error handling."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from finsentry.events.producer import RagEventProducer
from finsentry.events.schema import RagResponseEvent


def _make_event(status: str = "success") -> RagResponseEvent:
    return RagResponseEvent(
        event_id="evt-1",
        app_trace_id="req-1",
        timestamp_utc="2026-09-11T12:00:00+00:00",
        status=status,  # type: ignore[arg-type]
        endpoint="/v1/rag/query",
        query="Revenue?",
        ticker="AAPL",
        total_latency_ms=500,
    )


async def test_producer_disabled_mode_start_stop_emit_are_noops() -> None:
    """In disabled mode, start/stop/emit complete without error and touch no broker."""
    producer = RagEventProducer(mode="disabled", bootstrap_servers="localhost:9092")
    assert producer.mode == "disabled"
    await producer.start()
    event = _make_event()
    await producer.emit(event)  # must not raise
    await producer.stop()
    assert producer.mode == "disabled"


async def test_producer_kafka_mode_emit_serializes_event_correctly() -> None:
    """In kafka mode, emit() calls send_and_wait with the correct JSON payload."""
    mock_aio_producer = AsyncMock()
    mock_aio_producer.send_and_wait = AsyncMock()

    # Inject the mock producer directly; start() sets _producer, so bypass it here
    producer = RagEventProducer(mode="kafka", bootstrap_servers="localhost:9092")
    producer._producer = mock_aio_producer

    event = _make_event("success")
    await producer.emit(event)

    mock_aio_producer.send_and_wait.assert_called_once()
    call_args = mock_aio_producer.send_and_wait.call_args
    topic = call_args.args[0]
    payload = call_args.args[1]
    assert topic == "rag-responses"
    assert isinstance(payload, bytes)
    restored = RagResponseEvent.from_kafka_json(payload)
    assert restored.status == "success"
    assert restored.app_trace_id == "req-1"


async def test_producer_kafka_mode_swallows_send_error_and_logs_warning() -> None:
    """emit() swallows broker send errors and logs at WARNING; does not re-raise."""
    mock_aio_producer = AsyncMock()
    mock_aio_producer.send_and_wait = AsyncMock(side_effect=RuntimeError("broker gone"))

    producer = RagEventProducer(mode="kafka", bootstrap_servers="localhost:9092")
    producer._producer = mock_aio_producer

    with patch("finsentry.events.producer.log") as mock_log:
        await producer.emit(_make_event())  # must not raise
    mock_log.warning.assert_called_once()
    warning_msg = mock_log.warning.call_args.args[0]
    assert "RuntimeError" in warning_msg or "failed" in warning_msg.lower()


async def test_producer_kafka_mode_broker_unreachable_at_start_falls_back_to_disabled() -> None:
    """If the broker is unreachable at start(), mode transitions to disabled."""
    failing_inner = AsyncMock()
    failing_inner.start = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))

    mock_aiokafka = MagicMock()
    mock_aiokafka.AIOKafkaProducer = MagicMock(return_value=failing_inner)

    with patch.dict("sys.modules", {"aiokafka": mock_aiokafka}):
        producer = RagEventProducer(mode="kafka", bootstrap_servers="localhost:9999")
        await producer.start()

    assert producer.mode == "disabled"


async def test_producer_send_and_wait_uses_short_timeout() -> None:
    """AIOKafkaProducer is initialized with a bounded request_timeout_ms."""
    from finsentry.events.producer import _SEND_TIMEOUT_S

    captured_kwargs: dict[str, object] = {}

    class CapturingProducer:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        async def start(self) -> None:
            pass

    mock_aiokafka = MagicMock()
    mock_aiokafka.AIOKafkaProducer = CapturingProducer

    with patch.dict("sys.modules", {"aiokafka": mock_aiokafka}):
        producer = RagEventProducer(mode="kafka", bootstrap_servers="localhost:9092")
        await producer.start()

    assert "request_timeout_ms" in captured_kwargs
    timeout_ms = captured_kwargs["request_timeout_ms"]
    assert isinstance(timeout_ms, int)
    assert timeout_ms == int(_SEND_TIMEOUT_S * 1000)
