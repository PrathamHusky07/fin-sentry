"""
Frontier tier Kafka consumer: samples 10% of rag-responses events
deterministically, runs sampled events through the FrontierOrchestrator, and
publishes FrontierVerdictEvent to rag-frontier-verdicts.

Reuses RagEventConsumer (topic/group-id agnostic — see
finsentry/consumer/rag_event_consumer.py) rather than writing a new consumer
class, and the same resilience patterns as finsentry/consumer/main.py:
graceful shutdown on SIGTERM/SIGINT, schema_version guard (inherited from
RagEventConsumer), structured logging. Reads from the same source topic as
Flash (rag-responses) but under its own consumer group (frontier-tier) so
the two tiers commit offsets independently.

Run with:
    python -m finsentry.consumer.frontier_consumer

Environment variables:
    KAFKA_BOOTSTRAP_SERVERS      (default: localhost:9092)
    KAFKA_TOPIC                  (default: rag-responses)
    FRONTIER_CONSUMER_GROUP      (default: frontier-tier)
    KAFKA_FRONTIER_VERDICT_TOPIC (default: rag-frontier-verdicts)
    FRONTIER_HHEM_ENABLED        (default: false — see Day 5A M1 decision below)
    GEMINI_MODE                  (default: disabled)
    GEMINI_MODEL                 (default: gemini-3.6-flash)
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION        (default: global)
    GEMINI_API_KEY

HHEM default-disabled rationale: trust_remote_code=True loading fails in the
main venv's transformers 5.16.1 with an internal API incompatibility
(all_tied_weights_keys), confirmed in
docs/measurements/hhem-main-venv-load-attempt-d5a-m1.json. Set
FRONTIER_HHEM_ENABLED=true to have the consumer attempt the load anyway —
the adapter reports JudgeResult(status="unavailable") on failure rather than
crashing the consumer, but there is no point paying the ~6s load attempt on
every startup when the outcome is already known.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from finsentry.consumer.rag_event_consumer import RagEventConsumer
from finsentry.events.schema import RagResponseEvent
from finsentry.events.topics import RAG_FRONTIER_VERDICTS_TOPIC, RAG_RESPONSES_TOPIC
from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.adapters.hhem_adapter import HHEMAdapter
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.protocol import FrontierJudge
from finsentry.frontier.sampling import should_sample_for_frontier
from finsentry.frontier.types import FrontierVerdictEvent
from finsentry.rails.output.cost_governance import CostBudget

load_dotenv()

log = logging.getLogger(__name__)

_DEFAULT_FRONTIER_GROUP = "frontier-tier"


class FrontierVerdictProducer:
    """Thin wrapper around an aiokafka producer for FrontierVerdictEvent.

    Mirrors JudgeVerdictProducer (finsentry/judges/flash_judge.py) in shape,
    but is typed to FrontierVerdictEvent and kept separate rather than
    generalizing that class, to avoid any Flash-tier modification.
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: Any = None

    def inject_producer(self, producer: Any) -> None:
        self._producer = producer

    async def start(self) -> None:
        if self._producer is None:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

            self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def emit(self, verdict: FrontierVerdictEvent) -> None:
        if self._producer is None:
            log.warning(
                "FrontierVerdictProducer: not started, dropping verdict for %s",
                verdict.app_trace_id,
            )
            return
        try:
            await self._producer.send_and_wait(
                self._topic,
                value=verdict.to_kafka_json(),
                key=verdict.app_trace_id.encode(),
            )
        except Exception:
            log.exception(
                "FrontierVerdictProducer: failed to emit verdict for %s", verdict.app_trace_id
            )


def _build_judges() -> list[FrontierJudge]:
    judges: list[FrontierJudge] = []

    cost_budget = CostBudget()
    gemini = GeminiRubricAdapter(
        cost_budget=cost_budget,
        mode=os.getenv("GEMINI_MODE", "disabled"),
        model_name=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    judges.append(gemini)

    if os.getenv("FRONTIER_HHEM_ENABLED", "false").lower() == "true":
        judges.append(HHEMAdapter())
    else:
        log.info(
            "FRONTIER_HHEM_ENABLED is false — HHEM adapter not constructed "
            "(Day 5A M1 decision: transformers 5.x load incompatibility, see "
            "docs/measurements/hhem-main-venv-load-attempt-d5a-m1.json)"
        )

    return judges


def _unavailable_verdict(app_trace_id: str) -> FrontierVerdictEvent:
    return FrontierVerdictEvent(
        app_trace_id=app_trace_id,
        verdict="frontier_unavailable",
        per_judge_results=[],
        score_delta=None,
        disagreement_classification="insufficient_judges",
        evaluation_ts=datetime.now(UTC).isoformat(),
        frontier_sampling_decision_key=app_trace_id,
    )


async def _handle_event(
    event: RagResponseEvent,
    orchestrator: FrontierOrchestrator,
    verdict_producer: FrontierVerdictProducer,
) -> None:
    """Sample, guard, evaluate, and emit for one RagResponseEvent.

    The non-success guard mirrors FlashJudge's predicate (event.status ==
    "success" and event.answer) — a blocked/error event has no answer or
    citations to evaluate, and running it through a judge would both waste
    budget and score empty input.
    """
    if not should_sample_for_frontier(event.app_trace_id):
        return
    if not (event.status == "success" and event.answer):
        return
    try:
        verdict = await orchestrator.evaluate(event)
    except Exception:
        log.exception(
            "FrontierOrchestrator.evaluate raised for app_trace_id=%s", event.app_trace_id
        )
        verdict = _unavailable_verdict(event.app_trace_id)
    await verdict_producer.emit(verdict)
    log.info(
        "Frontier verdict emitted: app_trace_id=%s verdict=%s disagreement=%s",
        event.app_trace_id,
        verdict.verdict,
        verdict.disagreement_classification,
    )


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", RAG_RESPONSES_TOPIC)
    group = os.getenv("FRONTIER_CONSUMER_GROUP", _DEFAULT_FRONTIER_GROUP)
    verdict_topic = os.getenv("KAFKA_FRONTIER_VERDICT_TOPIC", RAG_FRONTIER_VERDICTS_TOPIC)

    orchestrator = FrontierOrchestrator(judges=_build_judges())
    verdict_producer = FrontierVerdictProducer(bootstrap_servers=bootstrap, topic=verdict_topic)
    consumer = RagEventConsumer(bootstrap_servers=bootstrap, topic=topic, group_id=group)

    await verdict_producer.start()

    async def _handle(event: RagResponseEvent) -> None:
        await _handle_event(event, orchestrator, verdict_producer)

    consumer.set_handler(_handle)

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("Shutdown signal received — stopping frontier consumer")
        asyncio.create_task(consumer.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    await consumer.start()
    log.info("Frontier consumer started — waiting for events")
    await consumer.run()
    await verdict_producer.stop()
    log.info("Frontier consumer exited cleanly")


if __name__ == "__main__":
    asyncio.run(_run())
