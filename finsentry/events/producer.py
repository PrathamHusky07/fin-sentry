"""
Kafka producer for RagResponseEvent.

Best-effort at-most-once delivery semantics — this is telemetry, not a durable
queue. asyncio.create_task on the caller side means emission runs off the request
path; on process crash, event loop cancellation, or container termination, in-flight
tasks can be lost. This is a deliberate trade-off: the reliability platform's own
event bus must never DoS the platform it evaluates. A durable transactional outbox
is deferred as a later consistency decision.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from finsentry.events.schema import RagResponseEvent

log = logging.getLogger(__name__)

_SEND_TIMEOUT_S: float = 5.0


class RagEventProducer:
    """Emit RagResponseEvent to Kafka. Best-effort at-most-once delivery.

    mode="disabled": no Kafka dependency; emit() logs at DEBUG and returns.
    mode="kafka": wraps AIOKafkaProducer. On broker unreachable at start(),
        self-transitions to disabled and logs at ERROR — the gateway continues
        rather than refusing to start.
    """

    def __init__(
        self,
        mode: Literal["kafka", "disabled"],
        bootstrap_servers: str,
        topic: str = "rag_responses",
    ) -> None:
        self._mode: Literal["kafka", "disabled"] = mode
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: Any = None  # AIOKafkaProducer instance when mode="kafka"

    @property
    def mode(self) -> Literal["kafka", "disabled"]:
        return self._mode

    async def start(self) -> None:
        if self._mode == "disabled":
            return
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

            producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                request_timeout_ms=int(_SEND_TIMEOUT_S * 1000),
            )
            await producer.start()
            self._producer = producer
            log.info("RagEventProducer started in kafka mode (topic=%s)", self._topic)
        except Exception as exc:
            log.error(
                "RagEventProducer failed to connect to broker at %s: %s. "
                "Falling back to disabled mode — events will not be emitted.",
                self._bootstrap_servers,
                exc,
            )
            self._mode = "disabled"

    async def stop(self) -> None:
        if self._producer is not None:
            try:
                await self._producer.stop()
            except Exception as exc:
                log.warning("RagEventProducer stop error: %s", exc)
            finally:
                self._producer = None

    async def emit(self, event: RagResponseEvent) -> None:
        if self._mode == "disabled":
            log.debug(
                "RagEventProducer disabled — skipping event app_trace_id=%s status=%s",
                event.app_trace_id,
                event.status,
            )
            return
        if self._producer is None:
            log.warning(
                "RagEventProducer.emit called but producer is not initialized; "
                "event dropped (app_trace_id=%s)",
                event.app_trace_id,
            )
            return
        try:
            payload = event.to_kafka_json()
            # _producer is an AIOKafkaProducer instance set in start(); using Any
            # for the call site avoids importing aiokafka at module level (optional dep).
            await self._producer.send_and_wait(self._topic, payload)
        except Exception as exc:
            log.warning(
                "RagEventProducer.emit failed (%s: %s); event dropped "
                "(app_trace_id=%s status=%s)",
                type(exc).__name__,
                exc,
                event.app_trace_id,
                event.status,
            )
