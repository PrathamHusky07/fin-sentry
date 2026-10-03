"""
FrontierOrchestrator: runs every registered FrontierJudge against one sampled
RagResponseEvent and reduces their JudgeResults into a single
FrontierVerdictEvent.

The verdict is not a weighted average. Disagreement between judges is
computed and surfaced explicitly (score_delta, disagreement_classification)
so a hiring-manager-readable trace shows WHY a verdict landed where it did,
not just a blended number that hides two judges pointing in opposite
directions.

Pass/fail/uncertain score thresholds below are architectural placeholders,
not calibrated values — Day 6's Cohen's kappa sweep against the human-labeled
golden set is where real thresholds get chosen. M1's job is a working
decision rule, not a tuned one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from finsentry.events.schema import RagResponseEvent
from finsentry.frontier.protocol import FrontierJudge
from finsentry.frontier.types import (
    Citation,
    DisagreementClassification,
    FrontierEvaluationInput,
    FrontierVerdict,
    FrontierVerdictEvent,
    JudgeResult,
)

log = logging.getLogger(__name__)

_DEFAULT_PER_JUDGE_TIMEOUT_S = 30.0

# PROVISIONAL thresholds, status: uncalibrated placeholders (see module
# docstring). Day 6's Cohen's kappa sweep against the golden set picks real
# values. Exact rule in effect until then:
#   mean_score >= _PASS_THRESHOLD (0.7)                -> frontier_pass
#   mean_score <= _FAIL_THRESHOLD (0.3)                -> frontier_fail
#   _FAIL_THRESHOLD < mean_score < _PASS_THRESHOLD     -> frontier_uncertain
#   score_delta <  _AGREEMENT_MAX_DELTA (0.15)          -> agreement
#   score_delta <  _MILD_DISAGREEMENT_MAX_DELTA (0.3)   -> mild_disagreement
#   score_delta >= _MILD_DISAGREEMENT_MAX_DELTA (0.3)   -> strong_disagreement
_PASS_THRESHOLD = 0.7
_FAIL_THRESHOLD = 0.3

_AGREEMENT_MAX_DELTA = 0.15
_MILD_DISAGREEMENT_MAX_DELTA = 0.3


def _build_evaluation_input(event: RagResponseEvent) -> FrontierEvaluationInput:
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

    @staticmethod
    def _classify_disagreement(
        successful_scores: list[float],
    ) -> tuple[DisagreementClassification, float | None]:
        if len(successful_scores) < 2:
            return "insufficient_judges", None
        score_delta = max(successful_scores) - min(successful_scores)
        if score_delta < _AGREEMENT_MAX_DELTA:
            return "agreement", score_delta
        if score_delta < _MILD_DISAGREEMENT_MAX_DELTA:
            return "mild_disagreement", score_delta
        return "strong_disagreement", score_delta

    @staticmethod
    def _decide_verdict(
        disagreement: DisagreementClassification,
        successful_scores: list[float],
    ) -> FrontierVerdict:
        if disagreement == "insufficient_judges":
            return "frontier_degraded" if successful_scores else "frontier_unavailable"
        if disagreement == "strong_disagreement":
            return "disagreement_review_needed"
        mean_score = sum(successful_scores) / len(successful_scores)
        if mean_score >= _PASS_THRESHOLD:
            return "frontier_pass"
        if mean_score <= _FAIL_THRESHOLD:
            return "frontier_fail"
        return "frontier_uncertain"

    async def evaluate(self, rag_event: RagResponseEvent) -> FrontierVerdictEvent:
        evaluation_input = _build_evaluation_input(rag_event)

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

        successful_scores = [
            r.faithfulness_score
            for r in judge_results
            if r.status == "success" and r.faithfulness_score is not None
        ]

        disagreement, score_delta = self._classify_disagreement(successful_scores)
        verdict = self._decide_verdict(disagreement, successful_scores)

        return FrontierVerdictEvent(
            app_trace_id=rag_event.app_trace_id,
            verdict=verdict,
            per_judge_results=judge_results,
            score_delta=score_delta,
            disagreement_classification=disagreement,
            evaluation_ts=datetime.now(UTC).isoformat(),
            frontier_sampling_decision_key=rag_event.app_trace_id,
        )
