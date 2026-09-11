"""
Reference-free Faithfulness rail: measures whether the generated answer's
factual claims are supported by the retrieved context.

Methodology: Es et al. 2023 (RAGAS paper), reference-free variant.
  1. Claim extraction: prompt Gemini to extract atomic claims from answer.
  2. Per-claim NLI: for each claim, prompt Gemini to verify against context.
  3. Score: supported_claims / total_claims (1.0 when total_claims == 0).

This is our own implementation of the RAGAS Faithfulness metric using the
google-genai SDK directly. The ragas PyPI package was evaluated and rejected
because it carries hard dependencies on openai>=1.0.0 and langchain_openai,
which violate the project's zero-cost constraint. See ADR 005.

Failure policy (consistent with ADR 004 taxonomy and config/rails.yml):
  - API key absent: skip (rail disabled at init).
  - 429 RESOURCE_EXHAUSTED: fail-open, status skipped_rate_limit. Do not retry.
  - Timeout (per-call 30s, total budget 120s): fail-open, skipped_timeout.
    Values reflect empirical latency of gemini-3.6-flash on Vertex AI (~10-15s
    per call observed in Session C smoke test; 12-16s per call in the
    Day-3-close smoke test).
  - 500/502/503 from Gemini: fail-open, skipped_upstream_error.
  - Safety filter rejection: fail-open, skipped_safety_filter.
  - 403/401 auth error: fail-open + ERROR log (config bug worth investigating).
  - Evaluator failure (malformed or non-list claim extraction response, malformed
    or ambiguous verdict response): fail-open, skipped_evaluator_error with
    sub_reason field distinguishing the exact failure type.
  - All fail-open paths annotate output_rail_trace with faithfulness_status.

Implementation: thin adapter over finsentry.judges.metrics.faithfulness_core.
evaluate_faithfulness() is the shared methodology; FaithfulnessRail exposes
a _generate() method so tests can patch it, and converts FaithfulnessResult
to RailDecision without duplicating the Es et al. logic.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from finsentry.judges.metrics.faithfulness_core import (
    CLAIM_EXTRACTION_PROMPT,
    CLAIM_VERIFICATION_PROMPT,
    FaithfulnessResult,
    _SkipError as _GeminiSkipError,
    _strip_json_fences,
    evaluate_faithfulness,
    make_gemini_generate_fn,
)
from finsentry.rails.base import RailDecision
from finsentry.rails.output.cost_governance import CostBudget

Mode = Literal["vertex", "developer", "disabled"]

log = logging.getLogger(__name__)

# Re-export prompt constants so existing tests that import from this module continue to work.
_CLAIM_EXTRACTION_PROMPT = CLAIM_EXTRACTION_PROMPT
_CLAIM_VERIFICATION_PROMPT = CLAIM_VERIFICATION_PROMPT

_PER_CALL_TIMEOUT = 30.0
_TOTAL_BUDGET = 120.0


class FaithfulnessRail:
    """Reference-free Faithfulness check on the (answer, retrieved_chunks) pair.

    Initialise with mode="disabled" to run without Gemini credentials.
    All Gemini errors fail-open so the gateway remains available.

    _generate() is kept as an instance method so test suites can patch it with
    patch.object(rail, "_generate", side_effect=...) without touching the
    faithfulness_core module.
    """

    name = "faithfulness"
    layer = "output"

    def __init__(
        self,
        mode: Mode,
        model_name: str,
        project: str | None = None,
        location: str = "global",
        api_key: str | None = None,
        threshold: float = 0.7,
        per_call_timeout_seconds: float = _PER_CALL_TIMEOUT,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._per_call_timeout = per_call_timeout_seconds
        self._mode = mode
        self._enabled = mode != "disabled"
        self._client: Any = None
        self._budget = CostBudget()
        if not self._enabled:
            return
        from google import genai

        if mode == "vertex":
            if not project:
                log.error("Faithfulness vertex mode requires GOOGLE_CLOUD_PROJECT")
                self._enabled = False
                self._mode = "disabled"
                return
            self._client = genai.Client(vertexai=True, project=project, location=location)
        elif mode == "developer":
            if not api_key:
                log.error("Faithfulness developer mode requires GEMINI_API_KEY")
                self._enabled = False
                self._mode = "disabled"
                return
            self._client = genai.Client(api_key=api_key)
        else:
            log.error("Faithfulness invalid mode %r — disabling", mode)
            self._enabled = False
            self._mode = "disabled"

    async def check(
        self,
        answer_text: str,
        retrieved_chunks: list[Any],  # list[RetrievedChunk]; avoid circular import
    ) -> RailDecision:
        if not self._enabled:
            return self._to_rail_decision(
                FaithfulnessResult(
                    score=0.0,
                    supported_claims=[],
                    unsupported_claims=[],
                    total_gemini_calls=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_thoughts_tokens=0,
                    status="skipped_no_key",
                    cost_report=self._budget.report(),
                )
            )

        chunk_texts = [
            f"[chunk_id={getattr(c, 'chunk_id', '')}] {getattr(c, 'text', '')}"
            for c in retrieved_chunks
        ]

        result = await evaluate_faithfulness(
            answer_text=answer_text,
            chunk_texts=chunk_texts,
            generate_fn=self._generate,
            cost_budget=self._budget,
            per_call_timeout=self._per_call_timeout,
            total_budget=_TOTAL_BUDGET,
        )

        return self._to_rail_decision(result)

    async def _generate(self, prompt: str) -> tuple[str, int, int, int]:
        """Raw Gemini API call. Instance method so tests can patch it with patch.object."""
        if self._client is None:
            raise _GeminiSkipError("skipped_no_key", {})
        gemini_fn = make_gemini_generate_fn(self._client, self._model_name)
        return await gemini_fn(prompt)

    def _to_rail_decision(self, result: FaithfulnessResult) -> RailDecision:
        """Convert a FaithfulnessResult to a RailDecision."""
        status = result.status

        if status == "complete":
            base_details: dict[str, Any] = {
                "score": result.score,
                "threshold": self._threshold,
                "supported_claims": result.supported_claims,
                "unsupported_claims": result.unsupported_claims,
                "gemini_calls": result.total_gemini_calls,
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "thoughts_tokens": result.total_thoughts_tokens,
                "cost": result.cost_report,
            }
            if not result.supported_claims and not result.unsupported_claims:
                return RailDecision(
                    outcome="pass",
                    reason="faithfulness: no claims to verify",
                    details={"faithfulness_status": "passed", **base_details},
                )
            if result.score < self._threshold:
                return RailDecision(
                    outcome="block",
                    reason="low_faithfulness",
                    details={"faithfulness_status": "blocked", **base_details},
                )
            return RailDecision(
                outcome="pass",
                reason="faithfulness check passed",
                details={"faithfulness_status": "passed", **base_details},
            )

        # Fail-open path (all skipped_* statuses)
        details: dict[str, Any] = {
            "faithfulness_status": status,
            "gemini_calls": result.total_gemini_calls,
            "input_tokens": result.total_input_tokens,
            "output_tokens": result.total_output_tokens,
            "thoughts_tokens": result.total_thoughts_tokens,
            "cost": result.cost_report,
        }
        if result.partial_supported is not None:
            details["supported_claims_partial"] = result.partial_supported
            details["unsupported_claims_partial"] = result.partial_unsupported or []
            details["claims_verified_before_skip"] = (
                len(result.partial_supported) + len(result.partial_unsupported or [])
            )
        if result.sub_reason is not None:
            details["sub_reason"] = result.sub_reason
            if status == "skipped_budget":
                details["ceiling"] = result.sub_reason
        if result.raw_response_snippet is not None:
            details["raw_response_snippet"] = result.raw_response_snippet
        return RailDecision(
            outcome="pass",
            reason=f"faithfulness fail-open: {status}",
            details=details,
        )
