"""
Real-Redpanda integration tests for the frontier consumer.

Requires the Docker Compose dev stack running (docker compose -f
docker-compose.dev.yml up -d). Excluded from the default
`pytest -m "not slow"` run (also tagged `slow`, see pytestmark below) — run
explicitly with `pytest -m integration`.

Wires RagEventConsumer + FrontierOrchestrator + FrontierVerdictProducer
directly (the same pieces finsentry/consumer/frontier_consumer.py._run()
wires) rather than invoking _run() itself, so a stub judge can be injected
and no real Gemini calls happen.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from finsentry.consumer.frontier_consumer import FrontierVerdictProducer
from finsentry.consumer.rag_event_consumer import RagEventConsumer
from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.sampling import should_sample_for_frontier
from finsentry.frontier.types import (
    FrontierEvaluationInput,
    FrontierVerdictEvent,
    JudgeHealth,
    JudgeResult,
)

# Tagged "slow" (not just "integration") so the existing `pytest -m "not slow"`
# exclusion already relied on throughout this repo also skips these by default;
# run explicitly with `pytest -m integration`.
pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.live_topics]

_BOOTSTRAP = "localhost:19092"
_SOURCE_TOPIC = "rag-responses"
_VERDICT_TOPIC = "rag-frontier-verdicts"


class _StubJudge:
    """Deterministic judge double — no real Gemini/HHEM calls in this test.

    Two instances both scoring >=0.7 (supported) are registered together so
    the orchestrator sees two agreeing usable decisions (ensemble_supported /
    agree_supported), matching the "both judges agree" case in
    tests/frontier/test_orchestrator.py rather than the one-judge
    single_judge path.
    """

    def __init__(self, judge_id: str, score: float) -> None:
        self.judge_id = judge_id
        self.judge_family = "stub"
        self.methodology = "stub"
        self._score = score

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status="success",
            decision="supported" if self._score >= 0.7 else "refuted",
            faithfulness_score=self._score,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


class _RaisingOrchestrator:
    """Simulates an orchestrator-level failure (not a judge-level one, which
    FrontierOrchestrator already handles internally and is covered by
    tests/frontier/test_orchestrator.py)."""

    async def evaluate(self, rag_event: RagResponseEvent) -> FrontierVerdictEvent:
        raise RuntimeError("simulated orchestrator failure")


def _ensure_topics() -> None:
    for topic in (_SOURCE_TOPIC, _VERDICT_TOPIC):
        subprocess.run(
            ["docker", "exec", "finsentry-redpanda", "rpk", "topic", "create", topic],
            capture_output=True,
            text=True,
            timeout=10,
        )


def _find_trace_id(sampled: bool) -> str:
    for _ in range(1000):
        candidate = str(uuid.uuid4())
        if should_sample_for_frontier(candidate) == sampled:
            return candidate
    raise AssertionError(f"could not find a trace id with should_sample_for_frontier == {sampled}")


def _event(app_trace_id: str) -> RagResponseEvent:
    return RagResponseEvent(
        event_id=str(uuid.uuid4()),
        app_trace_id=app_trace_id,
        timestamp_utc=datetime.now(UTC).isoformat(),
        status="success",
        endpoint="/v1/rag/query",
        query="integration test query",
        ticker="AAPL",
        retrieved_chunk_ids=["chunk-1"],
        retrieved_chunks_text=["Total net sales were $391,035 million."],
        answer="Total net sales were $391,035 million.",
        citations=[{"chunk_id": "chunk-1", "quote": "$391,035 million"}],
        total_latency_ms=100,
    )


async def _run_consumer_background(
    group_id: str, orchestrator: object
) -> tuple[RagEventConsumer, FrontierVerdictProducer, asyncio.Task[None]]:
    verdict_producer = FrontierVerdictProducer(bootstrap_servers=_BOOTSTRAP, topic=_VERDICT_TOPIC)
    await verdict_producer.start()

    consumer = RagEventConsumer(
        bootstrap_servers=_BOOTSTRAP, topic=_SOURCE_TOPIC, group_id=group_id
    )

    async def _handle(event: RagResponseEvent) -> None:
        if not should_sample_for_frontier(event.app_trace_id):
            return
        try:
            verdict = await orchestrator.evaluate(event)  # type: ignore[attr-defined]
        except Exception:
            from finsentry.consumer.frontier_consumer import _unavailable_verdict

            verdict = _unavailable_verdict(event.app_trace_id)
        await verdict_producer.emit(verdict)

    consumer.set_handler(_handle)
    await consumer.start()
    task = asyncio.create_task(consumer.run())
    await asyncio.sleep(2.0)  # let the consumer group join before publishing
    return consumer, verdict_producer, task


async def _publish_event(event: RagResponseEvent) -> None:
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=_BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(_SOURCE_TOPIC, value=event.to_kafka_json())
    finally:
        await producer.stop()


async def _consume_one_verdict(
    app_trace_id: str, timeout_s: float = 15.0
) -> dict[str, Any] | None:
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        _VERDICT_TOPIC,
        bootstrap_servers=_BOOTSTRAP,
        group_id=f"test-verdict-reader-{uuid.uuid4()}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                msg = await asyncio.wait_for(consumer.getone(), timeout=remaining)
            except TimeoutError:
                break
            payload = json.loads(msg.value.decode("utf-8"))
            if payload.get("app_trace_id") == app_trace_id:
                return payload
        return None
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_sampled_event_produces_frontier_verdict() -> None:
    _ensure_topics()
    trace_id = _find_trace_id(sampled=True)
    orchestrator = FrontierOrchestrator(
        judges=[_StubJudge("stub-a", 0.9), _StubJudge("stub-b", 0.85)]
    )
    group_id = f"frontier-tier-test-{uuid.uuid4()}"

    consumer, verdict_producer, task = await _run_consumer_background(group_id, orchestrator)
    try:
        await _publish_event(_event(trace_id))
        payload = await _consume_one_verdict(trace_id)
    finally:
        await consumer.stop()
        await verdict_producer.stop()
        task.cancel()

    assert payload is not None
    assert payload["verdict"] == "ensemble_supported"


@pytest.mark.asyncio
async def test_non_sampled_event_produces_no_verdict() -> None:
    _ensure_topics()
    trace_id = _find_trace_id(sampled=False)
    orchestrator = FrontierOrchestrator(
        judges=[_StubJudge("stub-a", 0.9), _StubJudge("stub-b", 0.85)]
    )
    group_id = f"frontier-tier-test-{uuid.uuid4()}"

    consumer, verdict_producer, task = await _run_consumer_background(group_id, orchestrator)
    try:
        await _publish_event(_event(trace_id))
        payload = await _consume_one_verdict(trace_id, timeout_s=8.0)
    finally:
        await consumer.stop()
        await verdict_producer.stop()
        task.cancel()

    assert payload is None


@pytest.mark.asyncio
async def test_orchestrator_failure_still_publishes_unavailable_verdict() -> None:
    _ensure_topics()
    trace_id = _find_trace_id(sampled=True)
    group_id = f"frontier-tier-test-{uuid.uuid4()}"

    consumer, verdict_producer, task = await _run_consumer_background(
        group_id, _RaisingOrchestrator()
    )
    try:
        await _publish_event(_event(trace_id))
        payload = await _consume_one_verdict(trace_id)
    finally:
        await consumer.stop()
        await verdict_producer.stop()
        task.cancel()

    assert payload is not None
    assert payload["verdict"] == "ensemble_insufficient"
