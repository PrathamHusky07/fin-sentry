from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from finsentry.consumer.frontier_consumer import FrontierVerdictProducer, _handle_event
from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult


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
            faithfulness_score=0.9,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


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
    assert producer.emitted[0].verdict == "frontier_degraded"
