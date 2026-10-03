"""
HHEM-2.1-Open frontier judge adapter.

Loading path established by Phase 0D's custom-code read (docs/measurements/
hhem-custom-code-phase0d.txt): HHEM's foundation model is google/flan-t5-base,
not DeBERTa. The model's own .predict([(premise, hypothesis), ...]) method
tokenizes internally via its own AutoTokenizer instance — there is no external
tokenizer to construct, and the bare forward(**kwargs) path (T5-shaped inputs
only) exists solely for HF text-classification pipeline compatibility.

Methodology: native NLI premise/hypothesis evaluation. premise is the
concatenated retrieved context; hypothesis is the generated answer. This is a
different evaluation methodology from the Gemini rubric adapter's absolute
scoring, which is the point — see finsentry/frontier/protocol.py.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from finsentry.frontier.types import (
    FrontierEvaluationInput,
    JudgeDecision,
    JudgeHealth,
    JudgeResult,
)

log = logging.getLogger(__name__)

_HHEM_MODEL_ID = "vectara/hallucination_evaluation_model"
_DEFAULT_TIMEOUT_S = 30.0
_HEALTH_WINDOW_S = 3600.0
_LIVENESS_PAIR = (
    "The capital of France is Paris.",
    "Paris is the capital of France.",
)

# Adapter-local decision thresholds, independent of GeminiRubricAdapter's
# (see finsentry/frontier/ensemble.py's module docstring on why no
# cross-judge shared threshold exists). HHEM's native NLI score is a
# continuous consistency probability, not an absolute rubric category, so
# these are provisional placeholders pending Day 6 calibration against the
# golden set -- the same numeric values as the Gemini adapter's thresholds
# here is coincidence, not a shared constant.
_SUPPORT_THRESHOLD = 0.7
_REFUTE_THRESHOLD = 0.3


def _decide(score: float) -> JudgeDecision:
    if score >= _SUPPORT_THRESHOLD:
        return "supported"
    if score <= _REFUTE_THRESHOLD:
        return "refuted"
    return "abstain"


class HHEMAdapter:
    judge_id = "hhem-2.1-open"
    judge_family = "hhem"
    methodology = "nli_premise_hypothesis"

    def __init__(self, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._model: Any = None
        self._load_error: str | None = None
        # (monotonic_ts, succeeded) for both evaluate() calls and health_check()
        # liveness pings — both are real model invocations, so both count.
        self._call_outcomes: list[tuple[float, bool]] = []
        self._last_success_ts: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            from transformers import AutoModelForSequenceClassification

            self._model = AutoModelForSequenceClassification.from_pretrained(
                _HHEM_MODEL_ID, trust_remote_code=True
            )
        except Exception as exc:
            self._load_error = str(exc)
            log.error("HHEMAdapter: model load failed — %s", exc)

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def _record_outcome(self, succeeded: bool) -> None:
        now = time.monotonic()
        self._call_outcomes.append((now, succeeded))
        cutoff = now - _HEALTH_WINDOW_S
        self._call_outcomes = [(t, s) for t, s in self._call_outcomes if t >= cutoff]
        if succeeded:
            from datetime import UTC, datetime

            self._last_success_ts = datetime.now(UTC).isoformat()

    def _error_rate_1h(self) -> float:
        if not self._call_outcomes:
            return 0.0
        failures = sum(1 for _, succeeded in self._call_outcomes if not succeeded)
        return failures / len(self._call_outcomes)

    async def _predict(self, premise: str, hypothesis: str) -> float:
        scores = await asyncio.wait_for(
            asyncio.to_thread(self._model.predict, [(premise, hypothesis)]),
            timeout=self._timeout_s,
        )
        return float(scores[0])

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        if self._model is None:
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="unavailable",
                error_detail=self._load_error or "model not loaded",
            )

        premise = "\n\n".join(evaluation_input.retrieved_context_chunks)
        hypothesis = evaluation_input.answer

        start = time.monotonic()
        try:
            score = await self._predict(premise, hypothesis)
            latency_ms = int((time.monotonic() - start) * 1000)
            if not math.isfinite(score) or not (0.0 <= score <= 1.0):
                self._record_outcome(succeeded=False)
                return JudgeResult(
                    judge_id=self.judge_id,
                    judge_family=self.judge_family,
                    methodology=self.methodology,
                    status="model_error",
                    error_detail=f"faithfulness_score_out_of_range: {score!r}",
                    latency_ms=latency_ms,
                )
            self._record_outcome(succeeded=True)
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="success",
                decision=_decide(score),
                faithfulness_score=score,
                evidence={"raw_score": score},
                latency_ms=latency_ms,
            )
        except TimeoutError:
            self._record_outcome(succeeded=False)
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="timeout",
                error_detail=f"evaluate() exceeded {self._timeout_s}s",
            )
        except Exception as exc:
            log.exception("HHEMAdapter: evaluate failed")
            self._record_outcome(succeeded=False)
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail=str(exc)[:500],
            )

    async def health_check(self) -> JudgeHealth:
        if self._model is None:
            return JudgeHealth(
                judge_id=self.judge_id,
                status="unavailable",
                last_success_ts=self._last_success_ts,
                error_rate_1h=1.0,
            )
        try:
            await self._predict(*_LIVENESS_PAIR)
            self._record_outcome(succeeded=True)
            return JudgeHealth(
                judge_id=self.judge_id,
                status="healthy",
                last_success_ts=self._last_success_ts,
                error_rate_1h=self._error_rate_1h(),
            )
        except Exception:
            self._record_outcome(succeeded=False)
            return JudgeHealth(
                judge_id=self.judge_id,
                status="degraded",
                last_success_ts=self._last_success_ts,
                error_rate_1h=self._error_rate_1h(),
            )
