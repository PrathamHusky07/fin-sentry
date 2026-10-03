from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.orchestrator import FrontierOrchestrator
from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult


class _StubJudge:
    """A FrontierJudge double: returns a canned JudgeResult, sleeps to
    simulate latency, or raises, depending on construction args.

    decision defaults to None, meaning "derive it from score the way a
    real adapter would" (>=0.7 supported, <=0.3 refuted, else abstain) --
    tests that only care about the decision can pass it directly instead
    of reverse-engineering a score for it.
    """

    def __init__(
        self,
        judge_id: str,
        score: float | None = None,
        decision: str | None = None,
        status: str = "success",
        sleep_s: float = 0.0,
        raise_exc: Exception | None = None,
    ) -> None:
        self.judge_id = judge_id
        self.judge_family = judge_id
        self.methodology = "stub"
        self._score = score
        self._status = status
        self._sleep_s = sleep_s
        self._raise_exc = raise_exc
        if decision is not None:
            self._decision = decision
        elif status != "success":
            self._decision = "unavailable"
        elif score is None:
            self._decision = "unavailable"
        elif score >= 0.7:
            self._decision = "supported"
        elif score <= 0.3:
            self._decision = "refuted"
        else:
            self._decision = "abstain"

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        if self._raise_exc is not None:
            raise self._raise_exc
        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status=self._status,  # type: ignore[arg-type]
            decision=self._decision,  # type: ignore[arg-type]
            faithfulness_score=self._score,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


def _rag_event(app_trace_id: str = "trace-1") -> RagResponseEvent:
    return RagResponseEvent(
        event_id="event-1",
        app_trace_id=app_trace_id,
        timestamp_utc=datetime.now(UTC).isoformat(),
        status="success",
        endpoint="/v1/rag/query",
        query="What was Apple's total net sales in fiscal year 2024?",
        ticker="AAPL",
        retrieved_chunk_ids=["chunk-1"],
        retrieved_chunks_text=["Total net sales were $391,035 million."],
        answer="Apple's total net sales in fiscal year 2024 were $391,035 million.",
        citations=[{"chunk_id": "chunk-1", "quote": "$391,035 million"}],
        total_latency_ms=1200,
    )


def test_two_judges_both_supported_yields_ensemble_supported() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.92),
            _StubJudge("judge-b", score=0.88),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_supported"
    assert verdict.disagreement_classification == "agree_supported"
    assert verdict.score_delta is not None
    assert len(verdict.per_judge_results) == 2


def test_two_judges_both_refuted_yields_ensemble_refuted() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.1),
            _StubJudge("judge-b", score=0.2),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_refuted"
    assert verdict.disagreement_classification == "agree_refuted"


def test_one_supported_one_refuted_yields_ensemble_mixed() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.95),
            _StubJudge("judge-b", score=0.1),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_mixed"
    assert verdict.disagreement_classification == "mixed_support_refute"
    # score_delta stays an analysis-only field, not the basis of the verdict --
    # this disagreement is detected from decision, not from how big the gap is.
    assert verdict.score_delta is not None
    assert verdict.score_delta >= 0.3


def test_both_judges_abstain_yields_ensemble_abstain() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.5),
            _StubJudge("judge-b", score=0.55),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_abstain"
    assert verdict.disagreement_classification == "abstain_dominated"


def test_one_judge_unavailable_yields_single_judge_path() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.9, status="success"),
            _StubJudge("judge-b", status="unavailable"),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_supported"
    assert verdict.disagreement_classification == "single_judge"
    assert verdict.score_delta is None
    assert {r.judge_id for r in verdict.per_judge_results} == {"judge-a", "judge-b"}


def test_all_judges_unavailable_yields_ensemble_insufficient() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", status="unavailable"),
            _StubJudge("judge-b", status="unavailable"),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_insufficient"
    assert verdict.disagreement_classification == "all_unavailable"
    assert len(verdict.per_judge_results) == 2


def test_judge_timeout_plus_a_success_yields_single_judge_path() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-slow", sleep_s=1.0),
            _StubJudge("judge-fast", score=0.8),
        ],
        per_judge_timeout_s=0.05,
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    results_by_id = {r.judge_id: r for r in verdict.per_judge_results}
    assert results_by_id["judge-slow"].status == "timeout"
    assert results_by_id["judge-slow"].decision == "unavailable"
    assert results_by_id["judge-fast"].status == "success"
    assert verdict.verdict == "ensemble_supported"
    assert verdict.disagreement_classification == "single_judge"


def test_judge_raising_exception_is_captured_as_model_error_without_crashing() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-broken", raise_exc=RuntimeError("boom")),
            _StubJudge("judge-ok", score=0.8),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    results_by_id = {r.judge_id: r for r in verdict.per_judge_results}
    assert results_by_id["judge-broken"].status == "model_error"
    assert results_by_id["judge-broken"].decision == "unavailable"
    assert "boom" in (results_by_id["judge-broken"].error_detail or "")
    assert results_by_id["judge-ok"].status == "success"
    assert verdict.verdict == "ensemble_supported"
    assert verdict.disagreement_classification == "single_judge"


def test_verdict_is_never_a_function_of_the_mean_score() -> None:
    """Two judges whose mean score (0.5) would have passed the old
    frontier_uncertain band, but whose actual decisions agree on refuted --
    the ensemble must follow the decisions, not the arithmetic mean."""
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.3, decision="refuted"),
            _StubJudge("judge-b", score=0.7, decision="refuted"),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_refuted"
    assert verdict.disagreement_classification == "agree_refuted"


def test_per_judge_evidence_is_preserved_in_the_emitted_verdict() -> None:
    orchestrator = FrontierOrchestrator(
        judges=[
            _StubJudge("judge-a", score=0.92),
            _StubJudge("judge-b", score=0.1),
        ]
    )
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    results_by_id = {r.judge_id: r for r in verdict.per_judge_results}
    assert results_by_id["judge-a"].faithfulness_score == 0.92
    assert results_by_id["judge-a"].decision == "supported"
    assert results_by_id["judge-b"].faithfulness_score == 0.1
    assert results_by_id["judge-b"].decision == "refuted"


def test_verdict_event_is_always_emitted_even_with_zero_judges_registered() -> None:
    orchestrator = FrontierOrchestrator(judges=[])
    verdict = asyncio.run(orchestrator.evaluate(_rag_event()))

    assert verdict.verdict == "ensemble_insufficient"
    assert verdict.disagreement_classification == "all_unavailable"
    assert verdict.per_judge_results == []
    assert verdict.app_trace_id == "trace-1"
