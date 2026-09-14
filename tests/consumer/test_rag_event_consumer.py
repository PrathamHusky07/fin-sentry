"""Tests for finsentry.consumer.rag_event_consumer.RagEventConsumer."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finsentry.consumer.rag_event_consumer import RagEventConsumer
from finsentry.events.schema import RagResponseEvent

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
        "query": "What is Apple revenue?",
        "ticker": "AAPL",
        "answer": "Apple revenue was $119.6B.",
        "total_latency_ms": 123,
    }
    defaults.update(overrides)
    return RagResponseEvent.model_validate(defaults)


def _make_kafka_msg(payload: dict[str, Any] | bytes, offset: int = 0) -> MagicMock:
    msg = MagicMock()
    if isinstance(payload, bytes):
        msg.value = payload
    else:
        msg.value = json.dumps(payload).encode()
    msg.offset = offset
    return msg


def _make_consumer(
    messages: list[MagicMock],
    max_concurrency: int = 5,
) -> RagEventConsumer:
    consumer = RagEventConsumer(
        bootstrap_servers="localhost:19092",
        topic="rag-responses",
        group_id="test-group",
        max_concurrency=max_concurrency,
    )

    fake_kafka = AsyncMock()
    fake_kafka.start = AsyncMock()
    fake_kafka.stop = AsyncMock()
    fake_kafka.commit = AsyncMock()

    # Async iterator that yields messages then stops
    async def _aiter() -> Any:
        for msg in messages:
            yield msg

    fake_kafka.__aiter__ = lambda self: _aiter()
    consumer.inject_consumer(fake_kafka)
    return consumer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_consumer_calls_handler_for_valid_event() -> None:
    """Valid RagResponseEvent messages are passed to the handler."""
    event = _make_event()
    msg = _make_kafka_msg(event.model_dump())
    received: list[RagResponseEvent] = []

    consumer = _make_consumer([msg])

    async def _handler(ev: RagResponseEvent) -> None:
        received.append(ev)

    consumer.set_handler(_handler)
    await consumer.start()
    await consumer.run()

    assert len(received) == 1
    assert received[0].app_trace_id == event.app_trace_id


@pytest.mark.anyio
async def test_consumer_drops_non_json_message() -> None:
    """Non-JSON bytes are dropped with a warning; handler is not called."""
    msg = _make_kafka_msg(b"not-json-at-all")
    received: list[RagResponseEvent] = []

    consumer = _make_consumer([msg])
    consumer.set_handler(lambda ev: received.append(ev))  # type: ignore[arg-type]
    await consumer.start()
    await consumer.run()

    assert received == []


@pytest.mark.anyio
async def test_consumer_drops_unsupported_schema_version() -> None:
    """Events with schema_version != 1.0 are dropped; handler is not called."""
    payload = _make_event().model_dump()
    payload["schema_version"] = "2.0"
    msg = _make_kafka_msg(payload)
    received: list[RagResponseEvent] = []

    consumer = _make_consumer([msg])
    consumer.set_handler(lambda ev: received.append(ev))  # type: ignore[arg-type]
    await consumer.start()
    await consumer.run()

    assert received == []


@pytest.mark.anyio
async def test_consumer_commits_after_each_message() -> None:
    """commit() is called once per message, and only after the handler for that message finishes."""
    call_log: list[str] = []

    async def _handler(ev: RagResponseEvent) -> None:
        call_log.append("handler")

    msgs = [_make_kafka_msg(_make_event().model_dump()) for _ in range(3)]
    # max_concurrency=1 gives deterministic sequential ordering: handler then commit per message
    consumer = _make_consumer(msgs, max_concurrency=1)

    async def _commit_tracking(*args: Any, **kwargs: Any) -> None:
        call_log.append("commit")

    consumer._consumer.commit.side_effect = _commit_tracking  # type: ignore[attr-defined]
    consumer.set_handler(_handler)
    await consumer.start()
    await consumer.run()

    assert consumer._consumer.commit.call_count == 3  # type: ignore[attr-defined]
    # With max_concurrency=1, each handler must complete before its commit fires
    assert call_log == ["handler", "commit", "handler", "commit", "handler", "commit"]


@pytest.mark.anyio
async def test_consumer_commits_after_handler_completes() -> None:
    """Within a single task, commit fires only after the handler coroutine finishes."""
    event = _make_event()
    msg = _make_kafka_msg(event.model_dump())

    handler_completed = False
    commit_saw_handler_done: list[bool] = []

    async def _handler(ev: RagResponseEvent) -> None:
        nonlocal handler_completed
        await asyncio.sleep(0.01)  # simulate async work
        handler_completed = True

    async def _commit_tracking(*args: Any, **kwargs: Any) -> None:
        commit_saw_handler_done.append(handler_completed)

    consumer = _make_consumer([msg])
    consumer._consumer.commit.side_effect = _commit_tracking  # type: ignore[attr-defined]
    consumer.set_handler(_handler)
    await consumer.start()
    await consumer.run()

    assert handler_completed is True
    assert commit_saw_handler_done == [True]


@pytest.mark.anyio
async def test_consumer_uses_auto_offset_reset_latest() -> None:
    """AIOKafkaConsumer is configured with auto_offset_reset='latest'.

    New consumer groups must not replay all historical events through Gemini
    on first startup. Historical replay requires an explicit rpk group seek.
    """
    from unittest.mock import patch as _patch

    consumer = RagEventConsumer(
        bootstrap_servers="localhost:9092",
        topic="rag-responses",
        group_id="test-group",
    )

    mock_instance = AsyncMock()
    mock_instance.start = AsyncMock()

    with _patch("aiokafka.AIOKafkaConsumer", return_value=mock_instance) as mock_consumer_cls:
        await consumer.start()

    call_kwargs = mock_consumer_cls.call_args[1]
    assert call_kwargs.get("auto_offset_reset") == "latest"


@pytest.mark.anyio
async def test_consumer_bounded_concurrency_semaphore() -> None:
    """Semaphore limits concurrent handler tasks to max_concurrency."""
    max_concurrency = 2
    concurrent_peak = 0
    current_concurrent = 0

    barrier = asyncio.Event()
    all_started = asyncio.Event()
    started_count = 0

    async def _slow_handler(ev: RagResponseEvent) -> None:
        nonlocal concurrent_peak, current_concurrent, started_count
        current_concurrent += 1
        if current_concurrent > concurrent_peak:
            concurrent_peak = current_concurrent
        started_count += 1
        if started_count == max_concurrency:
            all_started.set()
        await barrier.wait()
        current_concurrent -= 1

    msgs = [_make_kafka_msg(_make_event().model_dump()) for _ in range(3)]
    consumer = _make_consumer(msgs, max_concurrency=max_concurrency)
    consumer.set_handler(_slow_handler)
    await consumer.start()

    # Run in a separate task so we can control the barrier
    run_task = asyncio.create_task(consumer.run())
    await asyncio.wait_for(all_started.wait(), timeout=2.0)
    # At this point max_concurrency tasks are blocked; peak should not exceed it
    assert concurrent_peak <= max_concurrency
    barrier.set()
    await run_task


@pytest.mark.anyio
async def test_consumer_handler_exception_does_not_crash_consumer() -> None:
    """A handler that raises must not propagate; subsequent messages are still processed."""
    events = [_make_event(), _make_event()]
    msgs = [_make_kafka_msg(e.model_dump()) for e in events]
    received: list[str] = []

    call_count = 0

    async def _flaky(ev: RagResponseEvent) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient failure")
        received.append(ev.event_id)

    consumer = _make_consumer(msgs)
    consumer.set_handler(_flaky)
    await consumer.start()
    await consumer.run()

    # Second event was processed despite first handler crash
    assert len(received) == 1


@pytest.mark.anyio
async def test_consumer_stop_sets_shutdown_event() -> None:
    """stop() sets _shutdown_event so the run loop can exit cleanly."""
    consumer = _make_consumer([])
    await consumer.start()
    assert not consumer._shutdown_event.is_set()
    await consumer.stop()
    assert consumer._shutdown_event.is_set()


@pytest.mark.anyio
async def test_consumer_run_without_start_raises() -> None:
    """run() before start() raises RuntimeError immediately."""
    consumer = RagEventConsumer(
        bootstrap_servers="localhost:19092",
        topic="rag-responses",
        group_id="test-group",
    )
    with pytest.raises(RuntimeError, match="not started"):
        await consumer.run()


@pytest.mark.anyio
async def test_consumer_from_env_reads_env_vars() -> None:
    """consumer_from_env() picks up KAFKA_BOOTSTRAP_SERVERS and KAFKA_TOPIC."""
    from finsentry.consumer.rag_event_consumer import consumer_from_env

    with (
        patch.dict(
            "os.environ",
            {
                "KAFKA_BOOTSTRAP_SERVERS": "redpanda:9092",
                "KAFKA_TOPIC": "custom-topic",
                "KAFKA_CONSUMER_GROUP": "custom-group",
            },
        )
    ):
        c = consumer_from_env()

    assert c._bootstrap_servers == "redpanda:9092"
    assert c._topic == "custom-topic"
    assert c._group_id == "custom-group"
