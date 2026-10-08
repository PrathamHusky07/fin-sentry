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
    FRONTIER_LAG_ENTRY_THRESHOLD   (default: 1000 — consumer lag at or above which
                                    the sampling rate drops from 1 in 10 to 1 in 100)
    FRONTIER_LAG_RECOVERY_THRESHOLD (default: 200 — lag at or below which it returns)
    FAITHJUDGE_PEER_RETRIEVAL_ENABLED (default: true — Day 5A M2 FaithJudge
                                        peer-example retrieval; requires
                                        DATABASE_URL, degrades to zero-shot
                                        when unset or disabled)
    DATABASE_URL

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

from finsentry.consumer.lag_monitor import ConsumerLagMonitor
from finsentry.consumer.rag_event_consumer import RagEventConsumer
from finsentry.events.schema import RagResponseEvent
from finsentry.events.topics import RAG_FRONTIER_VERDICTS_TOPIC, RAG_RESPONSES_TOPIC
from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.adapters.hhem_adapter import HHEMAdapter
from finsentry.frontier.faithjudge.retriever import FinanceBenchPeerRetriever
from finsentry.frontier.faithjudge.types import PeerRetriever
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.protocol import FrontierJudge
from finsentry.frontier.sampling import (
    DEFAULT_ENTRY_LAG,
    DEFAULT_RECOVERY_LAG,
    AdaptiveSamplingController,
    should_sample_for_frontier,
)
from finsentry.frontier.types import FrontierVerdictEvent
from finsentry.rails.output.cost_governance import CostBudget

load_dotenv()

log = logging.getLogger(__name__)

_DEFAULT_FRONTIER_GROUP = "frontier-tier"
_LAG_POLL_INTERVAL_S = 5.0


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


def _build_peer_retriever() -> PeerRetriever | None:
    """Build the FaithJudge peer retriever, or None for a clean zero-shot degrade.

    Disabled by an explicit env flag or a missing DATABASE_URL — either way
    the consumer keeps running with peer_retrieval=None on every evaluation
    input, which GeminiRubricAdapter's v2_faithjudge prompt renders as an
    empty PEER EXAMPLES section (zero-shot).
    """
    if os.getenv("FAITHJUDGE_PEER_RETRIEVAL_ENABLED", "true").lower() != "true":
        log.info("FAITHJUDGE_PEER_RETRIEVAL_ENABLED is false — peer retrieval disabled")
        return None
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        log.info("DATABASE_URL not set — FaithJudge peer retrieval disabled")
        return None
    return FinanceBenchPeerRetriever(db_url=database_url)


def _unavailable_verdict(app_trace_id: str) -> FrontierVerdictEvent:
    return FrontierVerdictEvent(
        app_trace_id=app_trace_id,
        verdict="ensemble_insufficient",
        per_judge_results=[],
        score_delta=None,
        disagreement_classification="all_unavailable",
        evaluation_ts=datetime.now(UTC).isoformat(),
        frontier_sampling_decision_key=app_trace_id,
    )


async def _handle_event(
    event: RagResponseEvent,
    orchestrator: FrontierOrchestrator,
    verdict_producer: FrontierVerdictProducer,
    peer_retriever: PeerRetriever | None = None,
    sampler: AdaptiveSamplingController | None = None,
) -> None:
    """Sample, guard, retrieve peers, evaluate, and emit for one RagResponseEvent.

    sampler carries the lag-driven rate. None means the fixed normal rate.

    The non-success guard mirrors FlashJudge's predicate (event.status ==
    "success" and event.answer) — a blocked/error event has no answer or
    citations to evaluate, and running it through a judge would both waste
    budget and score empty input.

    peer_retriever is None when peer retrieval is disabled or unconfigured
    (see _build_peer_retriever) — evaluation then proceeds zero-shot, same
    as if retrieval had simply found no useful peers.
    """
    sampled = (
        sampler.should_sample(event.app_trace_id)
        if sampler is not None
        else should_sample_for_frontier(event.app_trace_id)
    )
    if not sampled:
        return
    if not (event.status == "success" and event.answer):
        return

    peer_retrieval = None
    if peer_retriever is not None:
        peer_retrieval = await peer_retriever.retrieve(event.query)

    try:
        verdict = await orchestrator.evaluate(event, peer_retrieval=peer_retrieval)
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


async def _poll_lag(
    sampler: AdaptiveSamplingController, monitor: ConsumerLagMonitor
) -> None:
    """Feed the sampler one reading of this consumer group's lag per interval.
    An unreadable monitor becomes a None reading, which holds the current rate."""
    while True:
        report = await monitor.fetch_lag()
        sampler.observe(report.total_lag if report.ok else None)
        await asyncio.sleep(_LAG_POLL_INTERVAL_S)


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", RAG_RESPONSES_TOPIC)
    group = os.getenv("FRONTIER_CONSUMER_GROUP", _DEFAULT_FRONTIER_GROUP)
    verdict_topic = os.getenv("KAFKA_FRONTIER_VERDICT_TOPIC", RAG_FRONTIER_VERDICTS_TOPIC)

    orchestrator = FrontierOrchestrator(judges=_build_judges())
    verdict_producer = FrontierVerdictProducer(bootstrap_servers=bootstrap, topic=verdict_topic)
    consumer = RagEventConsumer(bootstrap_servers=bootstrap, topic=topic, group_id=group)
    peer_retriever = _build_peer_retriever()
    sampler = AdaptiveSamplingController(
        entry_lag=int(os.getenv("FRONTIER_LAG_ENTRY_THRESHOLD", str(DEFAULT_ENTRY_LAG))),
        recovery_lag=int(os.getenv("FRONTIER_LAG_RECOVERY_THRESHOLD", str(DEFAULT_RECOVERY_LAG))),
    )
    lag_task = asyncio.create_task(_poll_lag(sampler, ConsumerLagMonitor(group, topic)))

    await verdict_producer.start()

    async def _handle(event: RagResponseEvent) -> None:
        await _handle_event(event, orchestrator, verdict_producer, peer_retriever, sampler)

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
    lag_task.cancel()
    await verdict_producer.stop()
    log.info("Frontier consumer exited cleanly")


if __name__ == "__main__":
    asyncio.run(_run())
