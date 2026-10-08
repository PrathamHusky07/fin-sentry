from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from finsentry.consumer.frontier_consumer import FrontierVerdictProducer, _handle_event
from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.faithjudge.types import PeerExample, PeerRetrievalResult
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.sampling import AdaptiveSamplingController, should_sample_for_frontier
from finsentry.frontier.types import (
    FrontierEvaluationInput,
    FrontierVerdictEvent,
    JudgeHealth,
    JudgeResult,
)


class _CountingJudge:
    judge_id = "stub"
    judge_family = "stub"
    methodology = "stub"

    def __init__(self) -> None:
        self.call_count = 0

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        self.call_count += 1
        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status="success",
            decision="supported",
            faithfulness_score=0.9,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


class _RecordingJudge:
    """Captures the FrontierEvaluationInput it was called with, for
    asserting on what peer_retrieval reached the judge."""

    judge_id = "stub"
    judge_family = "stub"
    methodology = "stub"

    def __init__(self) -> None:
        self.received_inputs: list[FrontierEvaluationInput] = []

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        self.received_inputs.append(evaluation_input)
        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status="success",
            decision="supported",
            faithfulness_score=0.9,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


class _StubPeerRetriever:
    dataset = "financebench"

    def __init__(self, result: PeerRetrievalResult) -> None:
        self._result = result
        self.call_count = 0

    async def retrieve(
        self, question: str, exclude_example_id: str | None = None
    ) -> PeerRetrievalResult:
        self.call_count += 1
        return self._result


class _RecordingVerdictProducer(FrontierVerdictProducer):
    def __init__(self) -> None:
        super().__init__(bootstrap_servers="unused", topic="unused")
        self.emitted: list[Any] = []

    async def emit(self, verdict: Any) -> None:  # type: ignore[override]
        self.emitted.append(verdict)


# A trace id known to sample (hash % 10 == 0). Found offline via
# should_sample_for_frontier; stable because sampling is a pure hash of the id.
_SAMPLED_TRACE_ID = "00000000-0000-0000-0000-000000000005"


def _event(status: str, answer: str = "An answer.") -> RagResponseEvent:
    return RagResponseEvent(
        event_id="event-1",
        app_trace_id=_SAMPLED_TRACE_ID,
        timestamp_utc=datetime.now(UTC).isoformat(),
        status=status,  # type: ignore[arg-type]
        endpoint="/v1/rag/query",
        query="What was Apple's total net sales?",
        ticker="AAPL",
        retrieved_chunk_ids=["chunk-1"],
        retrieved_chunks_text=["Total net sales were $391,035 million."],
        answer=answer,
        citations=[{"chunk_id": "chunk-1", "quote": "$391,035 million"}],
        total_latency_ms=100,
    )


async def test_blocked_event_produces_no_verdict_and_no_judge_call() -> None:
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(_event("blocked", answer=""), orchestrator, producer)

    assert judge.call_count == 0
    assert producer.emitted == []


async def test_error_event_produces_no_verdict_and_no_judge_call() -> None:
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(_event("error", answer=""), orchestrator, producer)

    assert judge.call_count == 0
    assert producer.emitted == []


async def test_success_event_with_empty_answer_produces_no_verdict() -> None:
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(_event("success", answer=""), orchestrator, producer)

    assert judge.call_count == 0
    assert producer.emitted == []


async def test_success_event_with_answer_produces_one_verdict() -> None:
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(_event("success"), orchestrator, producer)

    assert judge.call_count == 1
    assert len(producer.emitted) == 1
    assert producer.emitted[0].verdict == "ensemble_supported"


async def test_disabled_peer_retrieval_still_yields_a_valid_verdict() -> None:
    """peer_retriever=None (the disabled/unconfigured default) must degrade
    cleanly to zero-shot — no crash, a real verdict still comes out, and
    the judge sees peer_retrieval=None rather than a missing field."""
    judge = _RecordingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(_event("success"), orchestrator, producer, peer_retriever=None)

    assert len(producer.emitted) == 1
    assert producer.emitted[0].verdict == "ensemble_supported"
    assert len(judge.received_inputs) == 1
    assert judge.received_inputs[0].peer_retrieval is None


async def test_enabled_peer_retrieval_reaches_the_judge_on_the_evaluation_input() -> None:
    judge = _RecordingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()
    peer_result = PeerRetrievalResult(
        peers=[
            PeerExample(
                example_id="financebench_id_00005",
                question="peer question",
                expected_answer="peer answer",
                doc_id="CORNING_2022_10K",
                dataset="financebench",
                similarity=0.9,
            )
        ],
        rejected=[],
        k=3,
        similarity_threshold=0.75,
        leakage_ceiling=0.95,
        retrieval_latency_ms=5,
    )
    retriever = _StubPeerRetriever(peer_result)

    await _handle_event(_event("success"), orchestrator, producer, peer_retriever=retriever)

    assert retriever.call_count == 1
    assert len(judge.received_inputs) == 1
    assert judge.received_inputs[0].peer_retrieval is peer_result


def _id_sampled_at_normal_rate_only() -> str:
    for i in range(10_000):
        candidate = f"00000000-0000-0000-0000-{i:012d}"
        if should_sample_for_frontier(candidate, 10) and not should_sample_for_frontier(
            candidate, 100
        ):
            return candidate
    raise AssertionError("no such id")


async def test_reduced_rate_skips_a_trace_the_normal_rate_would_evaluate() -> None:
    trace_id = _id_sampled_at_normal_rate_only()
    event = _event("success").model_copy(update={"app_trace_id": trace_id})
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()
    sampler = AdaptiveSamplingController(entry_lag=10, recovery_lag=2, entry_readings=1)

    await _handle_event(event, orchestrator, producer, sampler=sampler)
    assert judge.call_count == 1

    sampler.observe(50)
    assert sampler.denominator == 100
    await _handle_event(event, orchestrator, producer, sampler=sampler)
    assert judge.call_count == 1


class _FailingPeerRetriever:
    dataset = "financebench"

    async def retrieve(
        self, question: str, exclude_example_id: str | None = None
    ) -> PeerRetrievalResult:
        raise ConnectionError("postgres is down")


class _RaisingKafkaProducer:
    """Stands in for AIOKafkaProducer. Counts the sends it was asked to make."""

    def __init__(self) -> None:
        self.attempts = 0

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.attempts += 1
        raise OSError("broker unreachable")


async def test_peer_retrieval_failure_records_an_unavailable_verdict_instead_of_dropping() -> None:
    judge = _CountingJudge()
    orchestrator = FrontierOrchestrator(judges=[judge])
    producer = _RecordingVerdictProducer()

    await _handle_event(
        _event("success"), orchestrator, producer, peer_retriever=_FailingPeerRetriever()
    )

    assert len(producer.emitted) == 1
    verdict = producer.emitted[0]
    assert verdict.app_trace_id == _SAMPLED_TRACE_ID
    assert verdict.verdict == "ensemble_insufficient"
    assert verdict.disagreement_classification == "all_unavailable"
    (result,) = verdict.per_judge_results
    assert result.judge_id == "stub"
    assert result.status == "unavailable"
    assert result.faithfulness_score is None and result.evidence is None
    assert result.error_detail == "peer retrieval failed: ConnectionError"
    # The explanation survives the wire format the dashboard reads.
    assert FrontierVerdictEvent.from_kafka_json(verdict.to_kafka_json()) == verdict


async def test_peer_retrieval_failure_is_not_judged_as_if_no_peers_existed() -> None:
    """A retrieval that raised means peers are unknown. A retrieval that succeeded and
    found none is a legitimate zero-shot evaluation. The two must not be conflated."""
    failed_judge = _CountingJudge()
    failed = _RecordingVerdictProducer()
    await _handle_event(
        _event("success"),
        FrontierOrchestrator(judges=[failed_judge]),
        failed,
        peer_retriever=_FailingPeerRetriever(),
    )
    assert failed_judge.call_count == 0

    empty = PeerRetrievalResult(
        peers=[],
        rejected=[],
        k=3,
        similarity_threshold=0.75,
        leakage_ceiling=0.95,
        retrieval_latency_ms=1,
    )
    ok_judge = _CountingJudge()
    ok = _RecordingVerdictProducer()
    await _handle_event(
        _event("success"),
        FrontierOrchestrator(judges=[ok_judge]),
        ok,
        peer_retriever=_StubPeerRetriever(empty),
    )
    assert ok_judge.call_count == 1
    assert ok.emitted[0].verdict == "ensemble_supported"
    assert ok.emitted[0].per_judge_results[0].status == "success"


async def test_a_failed_verdict_emit_propagates_instead_of_looking_processed() -> None:
    judge = _CountingJudge()
    kafka = _RaisingKafkaProducer()
    producer = FrontierVerdictProducer(bootstrap_servers="unused", topic="verdicts")
    producer.inject_producer(kafka)

    with pytest.raises(OSError, match="broker unreachable"):
        await _handle_event(_event("success"), FrontierOrchestrator(judges=[judge]), producer)

    assert kafka.attempts == 1


async def test_emit_before_the_producer_is_started_raises() -> None:
    producer = FrontierVerdictProducer(bootstrap_servers="unused", topic="verdicts")
    verdict = FrontierOrchestrator(judges=[]).unavailable_verdict(_event("success"), "x")
    with pytest.raises(RuntimeError, match="not started"):
        await producer.emit(verdict)


async def test_failed_unavailable_verdict_emit_also_propagates() -> None:
    producer = FrontierVerdictProducer(bootstrap_servers="unused", topic="verdicts")
    producer.inject_producer(_RaisingKafkaProducer())

    with pytest.raises(OSError):
        await _handle_event(
            _event("success"),
            FrontierOrchestrator(judges=[_CountingJudge()]),
            producer,
            peer_retriever=_FailingPeerRetriever(),
        )


async def test_a_failed_verdict_emit_leaves_the_source_offset_uncommitted() -> None:
    """End to end through the consumer: offset 101 cannot emit its verdict, so the
    commit stops at 101 (next to read after 100) and never covers 101 or 102."""
    from aiokafka import TopicPartition

    from tests.consumer.test_rag_event_consumer import _make_consumer, _make_kafka_msg

    class _FlakyProducer:
        def __init__(self) -> None:
            self.sent: list[bytes] = []

        async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
            if key == b"trace-101":
                raise OSError("broker unreachable")
            self.sent.append(key)

    sampler = AdaptiveSamplingController(entry_lag=10, recovery_lag=2)
    sampler.should_sample = lambda _trace_id: True  # type: ignore[method-assign]

    messages = [
        _make_kafka_msg(
            _event("success").model_copy(update={"app_trace_id": f"trace-{o}"}).model_dump(),
            offset=o,
        )
        for o in (100, 101, 102)
    ]
    consumer = _make_consumer(messages, max_attempts=2)
    commits: list[dict[Any, int]] = []

    async def _commit(offsets: dict[Any, int]) -> None:
        commits.append(dict(offsets))

    consumer._consumer.commit.side_effect = _commit
    kafka = _FlakyProducer()
    producer = FrontierVerdictProducer(bootstrap_servers="unused", topic="verdicts")
    producer.inject_producer(kafka)
    orchestrator = FrontierOrchestrator(judges=[_CountingJudge()])

    async def _handle(ev: RagResponseEvent) -> None:
        await _handle_event(ev, orchestrator, producer, sampler=sampler)

    consumer.set_handler(_handle)
    await consumer.start()
    await consumer.run()

    assert commits == [{TopicPartition("rag-responses", 0): 101}]
    # 102 was processed and emitted, but it is held behind 101, not lost.
    assert sorted(kafka.sent) == [b"trace-100", b"trace-102"]
