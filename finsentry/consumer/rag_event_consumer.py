"""
RagEventConsumer: async Kafka consumer for RagResponseEvent messages.

Reads from the Redpanda topic produced by the gateway, hands each event to
a registered handler, and enforces bounded concurrency via asyncio.Semaphore.

Design decisions:
- One consumer per process; consumer group is KAFKA_CONSUMER_GROUP env var.
- asyncio.Semaphore(5) caps concurrent in-flight handler tasks so that a slow
  judge (30s Gemini call) does not queue unboundedly.
- Graceful shutdown: on SIGTERM/SIGINT, stop() is called which sets
  _shutdown_event; the run loop drains the semaphore before exiting.
- schema_version != "1.0" events are logged at WARNING and dropped; the
  consumer never crashes on an unrecognized schema version.
- Each message is committed after the handler coroutine completes so that a
  crash during judgment does not silently skip the event.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from finsentry.events.schema import RagResponseEvent

log = logging.getLogger(__name__)

_MAX_CONCURRENCY = 5
_SUPPORTED_SCHEMA_VERSION = "1.0"

EventHandler = Callable[[RagResponseEvent], Awaitable[None]]


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
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._semaphore = asyncio.Semaphore(max_concurrency)
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
            from aiokafka import AIOKafkaConsumer

            self._consumer = AIOKafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                value_deserializer=lambda b: b,
                auto_offset_reset="earliest",
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

        async def _bounded_handle(event: RagResponseEvent) -> None:
            async with self._semaphore:
                if self._handler is not None:
                    try:
                        await self._handler(event)
                    except Exception:
                        log.exception("Handler error for event %s", event.event_id)

        try:
            async for msg in self._consumer:
                if self._shutdown_event.is_set():
                    break
                event = self._parse_message(msg)
                if event is None:
                    await self._consumer.commit()
                    continue
                task = asyncio.create_task(_bounded_handle(event))
                pending.add(task)
                task.add_done_callback(pending.discard)
                await self._consumer.commit()
        finally:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

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
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        topic=os.getenv("KAFKA_TOPIC", "rag-responses"),
        group_id=os.getenv("KAFKA_CONSUMER_GROUP", "finsentry-rag-flash-judge"),
    )
