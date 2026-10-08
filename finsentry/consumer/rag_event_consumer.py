"""
RagEventConsumer: async Kafka consumer for RagResponseEvent messages.

Reads from the Redpanda topic produced by the gateway, hands each event to
a registered handler, and enforces bounded concurrency via asyncio.Semaphore.

Design decisions:
- One consumer per process; consumer group is KAFKA_CONSUMER_GROUP env var.
- asyncio.Semaphore(5) caps concurrent in-flight handler tasks so that a slow
  judge (30s Gemini call) does not queue unboundedly. The slot is taken before
  the task is spawned, so a saturated pool stops the fetch loop and the backlog
  stays in Redpanda, where consumer lag can see it.
- Graceful shutdown: on SIGTERM/SIGINT, stop() is called which sets
  _shutdown_event; the run loop drains the semaphore before exiting.
- schema_version != "1.0" events are logged at WARNING and dropped; the
  consumer never crashes on an unrecognized schema version.
- Offsets are committed per partition and only up to the contiguous completed
  frontier. Handlers finish out of order, so "this message is done" is not the
  same as "this offset may be committed": committing past a still-running or
  failed message would skip it forever after a crash. Delivery is at-least-once
  and duplicate-tolerant, not exactly-once. A handler that keeps failing holds
  the frontier at its offset (it is redelivered after a restart) while later
  messages keep being processed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from finsentry.events.schema import RagResponseEvent
from finsentry.events.topics import DEFAULT_CONSUMER_GROUP, RAG_RESPONSES_TOPIC

log = logging.getLogger(__name__)

_MAX_CONCURRENCY = 5
_MAX_HANDLER_ATTEMPTS = 3
_RETRY_DELAY_S = 2.0
_SUPPORTED_SCHEMA_VERSION = "1.0"

EventHandler = Callable[[RagResponseEvent], Awaitable[None]]
_Partition = tuple[str, int]


class _OffsetTracker:
    """Tracks which fetched offsets have finished and how far each partition may
    be committed.

    Offsets are registered in fetch order. The commit frontier of a partition is
    the offset after the last one in an unbroken run of finished offsets from the
    oldest uncommitted message. Contiguity is judged on the registered sequence,
    not on arithmetic, so offset gaps in the log (transaction markers, compaction)
    never block it. Offsets are Kafka "next to read" values: finishing offset 101
    makes 102 eligible to commit.
    """

    def __init__(self) -> None:
        self._window: dict[_Partition, dict[int, bool]] = {}
        self._frontier: dict[_Partition, int] = {}
        self._committed: dict[_Partition, int] = {}

    def register(self, tp: _Partition, offset: int) -> None:
        # An offset below the frontier is a redelivery of something already
        # eligible. It is processed again but needs no tracking.
        if offset < self._frontier.get(tp, offset):
            return
        self._window.setdefault(tp, {}).setdefault(offset, False)

    def complete(self, tp: _Partition, offset: int) -> None:
        window = self._window.get(tp)
        if window is None or offset not in window:
            return
        window[offset] = True
        while window:
            head = next(iter(window))
            if not window[head]:
                break
            del window[head]
            self._frontier[tp] = head + 1

    def commit_target(self, tp: _Partition) -> int | None:
        frontier = self._frontier.get(tp)
        if frontier is None or frontier <= self._committed.get(tp, -1):
            return None
        return frontier

    def mark_committed(self, tp: _Partition, offset: int) -> None:
        self._committed[tp] = offset


class RagEventConsumer:
    """Async Kafka consumer wrapping aiokafka.AIOKafkaConsumer.

    Usage::

        consumer = RagEventConsumer(bootstrap_servers="localhost:9092",
                                     topic="rag-responses",
                                     group_id="finsentry-rag-flash-judge")
        consumer.set_handler(my_handler)
        await consumer.start()
        await consumer.run()          # blocks until stop() is called
        await consumer.stop()
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        max_concurrency: int = _MAX_CONCURRENCY,
        max_attempts: int = _MAX_HANDLER_ATTEMPTS,
        retry_delay_s: float = _RETRY_DELAY_S,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_attempts = max_attempts
        self._retry_delay_s = retry_delay_s
        self._tracker = _OffsetTracker()
        # Commits are serialized so a slow older commit can never land after a newer one.
        self._commit_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._handler: EventHandler | None = None
        self._consumer: Any = None  # aiokafka.AIOKafkaConsumer; injected for testability

    def set_handler(self, handler: EventHandler) -> None:
        self._handler = handler

    def inject_consumer(self, consumer: Any) -> None:
        """Inject a pre-built consumer (used in tests to avoid real Kafka)."""
        self._consumer = consumer

    async def start(self) -> None:
        """Start the underlying Kafka consumer (connects and subscribes)."""
        if self._consumer is None:
            from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]

            self._consumer = AIOKafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                value_deserializer=lambda b: b,
                # "latest" prevents a new consumer group from replaying every
                # historical event through Gemini on first startup — that would
                # burn Vertex quota on events the operator did not intend to
                # re-evaluate. For historical replay, reset offsets manually:
                #   rpk group seek --to earliest <group>
                auto_offset_reset="latest",
                enable_auto_commit=False,
            )
        await self._consumer.start()
        log.info("RagEventConsumer started — topic=%s group=%s", self._topic, self._group_id)

    async def stop(self) -> None:
        """Signal the run loop to exit and stop the consumer."""
        self._shutdown_event.set()
        if self._consumer is not None:
            await self._consumer.stop()
            log.info("RagEventConsumer stopped")

    async def run(self) -> None:
        """Main consume loop. Blocks until stop() is called."""
        if self._consumer is None:
            raise RuntimeError("Consumer not started — call start() first")

        pending: set[asyncio.Task[None]] = set()

        async def _handle_and_commit(msg: Any, event: RagResponseEvent) -> None:
            # The caller already holds a semaphore slot for this task.
            tp = (msg.topic, msg.partition)
            try:
                if await self._run_handler(event, msg.offset):
                    self._tracker.complete(tp, msg.offset)
                    await self._commit_frontier(tp)
                else:
                    log.error(
                        "Handler gave up on event %s at %s offset %s. The offset stays "
                        "uncommitted and the event is redelivered after a restart.",
                        event.event_id,
                        tp,
                        msg.offset,
                    )
            finally:
                self._semaphore.release()

        try:
            async for msg in self._consumer:
                if self._shutdown_event.is_set():
                    break
                tp = (msg.topic, msg.partition)
                self._tracker.register(tp, msg.offset)
                event = self._parse_message(msg)
                if event is None:
                    # An invalid message is dropped, but its offset still has to be
                    # reached in order before the frontier can move past it.
                    self._tracker.complete(tp, msg.offset)
                    await self._commit_frontier(tp)
                    continue
                # Take the slot before spawning the task, so a slow judge stops the
                # fetch loop instead of piling up tasks. Kafka lag then measures the
                # real backlog, which is what the frontier sampling controller reads.
                await self._semaphore.acquire()
                task = asyncio.create_task(_handle_and_commit(msg, event))
                pending.add(task)
                task.add_done_callback(pending.discard)
        finally:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _run_handler(self, event: RagResponseEvent, offset: int) -> bool:
        """Run the handler, retrying a failure a bounded number of times. Returns
        whether it succeeded. Retries stay inside the caller's slot, so a failing
        dependency slows the fetch loop instead of widening concurrency."""
        if self._handler is None:
            return True
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._handler(event)
                return True
            except Exception:
                log.exception(
                    "Handler error for event %s offset %s (attempt %d of %d)",
                    event.event_id,
                    offset,
                    attempt,
                    self._max_attempts,
                )
            if attempt == self._max_attempts or self._shutdown_event.is_set():
                break
            await asyncio.sleep(self._retry_delay_s * attempt)
        return False

    async def _commit_frontier(self, tp: _Partition) -> None:
        """Commit the partition's contiguous frontier if it moved past what is
        already committed. A failed commit is logged and leaves the target in
        place, so the next completion on this partition retries it."""
        from aiokafka import TopicPartition

        async with self._commit_lock:
            offset = self._tracker.commit_target(tp)
            if offset is None:
                return
            try:
                await self._consumer.commit({TopicPartition(*tp): offset})
            except Exception:
                log.exception(
                    "Commit failed for %s offset %s. Retried on the next completion", tp, offset
                )
                return
            self._tracker.mark_committed(tp, offset)

    def _parse_message(self, msg: Any) -> RagResponseEvent | None:
        """Deserialize and validate a Kafka message. Returns None to drop."""
        try:
            raw = json.loads(msg.value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("RagEventConsumer: non-JSON message on offset %s — dropping", msg.offset)
            return None

        version = raw.get("schema_version", "")
        if version != _SUPPORTED_SCHEMA_VERSION:
            log.warning(
                "RagEventConsumer: unsupported schema_version=%r offset=%s — dropping",
                version,
                msg.offset,
            )
            return None

        try:
            return RagResponseEvent.model_validate(raw)
        except Exception:
            log.warning(
                "RagEventConsumer: validation error offset=%s — dropping", msg.offset, exc_info=True
            )
            return None


def consumer_from_env() -> RagEventConsumer:
    """Build a RagEventConsumer from environment variables."""
    return RagEventConsumer(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        topic=os.getenv("KAFKA_TOPIC", RAG_RESPONSES_TOPIC),
        group_id=os.getenv("KAFKA_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP),
    )
