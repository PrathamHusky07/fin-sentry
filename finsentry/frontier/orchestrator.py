"""
FrontierOrchestrator: runs every registered FrontierJudge against one sampled
RagResponseEvent and reduces their JudgeResults into a single
FrontierVerdictEvent.

The verdict is never a weighted average. Day 5 M3 replaced the orchestrator's
own mean-score reduction with finsentry/frontier/ensemble.py's
decide_ensemble(): a reduction over each judge's categorical decision
(supported/refuted/abstain/unavailable), computed independently by each
adapter from its own provisional thresholds. Averaging HHEM's NLI score
against Gemini's absolute rubric score would blend two numbers that are not
on a shared scale just because both happen to range over [0, 1] -- see
ensemble.py's module docstring for the full argument. The orchestrator's
only job here is running judges concurrently with per-judge timeouts and
handing their results to decide_ensemble(); it has no decision logic of
its own.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.ensemble import decide_ensemble
from finsentry.frontier.faithjudge.types import PeerRetrievalResult
from finsentry.frontier.protocol import FrontierJudge
from finsentry.frontier.types import (
    Citation,
    FrontierEvaluationInput,
    FrontierVerdictEvent,
    JudgeResult,
)

log = logging.getLogger(__name__)

_DEFAULT_PER_JUDGE_TIMEOUT_S = 30.0


def _build_evaluation_input(
    event: RagResponseEvent, peer_retrieval: PeerRetrievalResult | None
) -> FrontierEvaluationInput:
    chunk_text_by_id = dict(
        zip(event.retrieved_chunk_ids, event.retrieved_chunks_text, strict=False)
    )
    citations = [
        Citation(
            chunk_id=str(c.get("chunk_id", "")),
            quote=str(c.get("quote", "")),
            retrieved_text=chunk_text_by_id.get(str(c.get("chunk_id", "")), ""),
        )
        for c in event.citations
    ]
    return FrontierEvaluationInput(
        app_trace_id=event.app_trace_id,
        question=event.query,
        answer=event.answer,
        citations=citations,
        retrieved_context_chunks=event.retrieved_chunks_text,
        original_rag_event_ts=event.timestamp_utc,
        peer_retrieval=peer_retrieval,
    )


class FrontierOrchestrator:
    """Holds a registry of FrontierJudge instances. Adding or removing a judge
    is a change to the list passed into __init__, never a change to this class.
    """

    def __init__(
        self,
        judges: list[FrontierJudge],
        per_judge_timeout_s: float = _DEFAULT_PER_JUDGE_TIMEOUT_S,
    ) -> None:
        self._judges = judges
        self._per_judge_timeout_s = per_judge_timeout_s

    async def _run_judge(
        self, judge: FrontierJudge, evaluation_input: FrontierEvaluationInput
    ) -> JudgeResult:
        """Run one judge with a timeout, converting any raise into a JudgeResult.

        A judge adapter is specified to never raise (it catches its own
        errors), but the orchestrator does not trust that contract blindly —
        a judge implementation bug must not crash the whole evaluation.
        """
        try:
            return await asyncio.wait_for(
                judge.evaluate(evaluation_input), timeout=self._per_judge_timeout_s
            )
        except TimeoutError:
            return JudgeResult(
                judge_id=judge.judge_id,
                judge_family=judge.judge_family,
                methodology=judge.methodology,
                status="timeout",
                error_detail=f"orchestrator timeout after {self._per_judge_timeout_s}s",
            )
        except Exception as exc:
            log.exception("FrontierOrchestrator: judge %s raised", judge.judge_id)
            return JudgeResult(
                judge_id=judge.judge_id,
                judge_family=judge.judge_family,
                methodology=judge.methodology,
                status="model_error",
                error_detail=str(exc)[:500],
            )

    async def evaluate(
        self,
        rag_event: RagResponseEvent,
        peer_retrieval: PeerRetrievalResult | None = None,
    ) -> FrontierVerdictEvent:
        """Evaluate one sampled RagResponseEvent.

        peer_retrieval is pre-fetched by the caller (the frontier consumer)
        and threaded onto the FrontierEvaluationInput unchanged — this
        orchestrator never calls a PeerRetriever itself and has no
        knowledge of golden_set, embeddings, or contamination control.
        """
        evaluation_input = _build_evaluation_input(rag_event, peer_retrieval)

        start = time.monotonic()
        judge_results: list[JudgeResult] = []
        if self._judges:
            judge_results = list(
                await asyncio.gather(
                    *(self._run_judge(judge, evaluation_input) for judge in self._judges),
                    return_exceptions=False,
                )
            )
        eval_latency_ms = int((time.monotonic() - start) * 1000)
        log.debug(
            "FrontierOrchestrator: evaluated app_trace_id=%s in %dms with %d judges",
            rag_event.app_trace_id,
            eval_latency_ms,
            len(self._judges),
        )

        return self._verdict_event(rag_event, judge_results)

    def unavailable_verdict(self, rag_event: RagResponseEvent, reason: str) -> FrontierVerdictEvent:
        """Verdict for a sampled event that could not be evaluated, so it is still
        recorded. Every registered judge is listed as unavailable with the reason,
        and the ensemble reduction gives its usual all-unavailable outcome. No judge
        ran, so no score or decision is claimed."""
        results = [
            JudgeResult(
                judge_id=judge.judge_id,
                judge_family=judge.judge_family,
                methodology=judge.methodology,
                status="unavailable",
                error_detail=reason,
            )
            for judge in self._judges
        ]
        return self._verdict_event(rag_event, results)

    @staticmethod
    def _verdict_event(
        rag_event: RagResponseEvent, judge_results: list[JudgeResult]
    ) -> FrontierVerdictEvent:
        outcome = decide_ensemble(judge_results)
        return FrontierVerdictEvent(
            app_trace_id=rag_event.app_trace_id,
            verdict=outcome.verdict,
            per_judge_results=outcome.per_judge_results,
            score_delta=outcome.score_delta,
            disagreement_classification=outcome.disagreement_taxonomy,
            evaluation_ts=datetime.now(UTC).isoformat(),
            frontier_sampling_decision_key=rag_event.app_trace_id,
        )
