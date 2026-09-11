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
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from finsentry.rails.base import RailDecision
from finsentry.rails.output.cost_governance import CostBudget

Mode = Literal["vertex", "developer", "disabled"]

log = logging.getLogger(__name__)

_CLAIM_EXTRACTION_PROMPT = """\
Extract atomic factual claims from the following answer. Return ONLY a JSON array of \
strings, where each string is one atomic factual claim. Limit to at most 10 claims. \
If the answer contains no verifiable factual claims, return an empty array [].

Answer:
{answer}

Return only a JSON array of strings, no other text."""

_CLAIM_VERIFICATION_PROMPT = """\
Given the following context, does the claim hold? Answer "yes" or "no" with a one-sentence \
rationale.

Context:
{context}

Claim: {claim}

Respond in this exact JSON format:
{{"verdict": "yes" or "no", "rationale": "one sentence"}}"""

def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences that Gemini may wrap around JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence (```json or ```)
        lines = lines[1:]
        # Drop closing fence if present
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


_MAX_CLAIMS = 10
# Per-call and total budget defaults.
# gemini-3.6-flash is a thinking model (~10-15s per call on the Developer API free tier).
# These defaults are intentionally generous; the smoke test verifies empirical latency.
_PER_CALL_TIMEOUT = 30.0  # seconds per Gemini API call
_TOTAL_BUDGET = 120.0  # seconds total for the entire rail


class FaithfulnessRail:
    """Reference-free Faithfulness check on the (answer, retrieved_chunks) pair.

    Initialise with api_key=None or api_key="" to run in disabled mode.
    All Gemini errors fail-open so the gateway remains available.
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
            return self._fail_open_response("skipped_no_key", 0, 0, 0, 0)

        deadline = time.monotonic() + _TOTAL_BUDGET
        total_input_tokens = 0
        total_output_tokens = 0
        total_thoughts_tokens = 0
        total_calls = 0

        context_text = "\n\n".join(
            f"[chunk_id={getattr(c, 'chunk_id', '')}] {getattr(c, 'text', '')}"
            for c in retrieved_chunks
        )

        # Step 1: claim extraction
        extract_prompt = _CLAIM_EXTRACTION_PROMPT.format(answer=answer_text)
        try:
            projected = self._estimate_next_call_cost()
            ok, ceiling_reason = self._budget.can_proceed(projected)
            if not ok:
                raise _GeminiSkipError("skipped_budget", {"ceiling": ceiling_reason})
            claims_raw, in_tok, out_tok, thoughts_tok = await self._call_gemini(
                extract_prompt, deadline
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_thoughts_tokens += thoughts_tok
            total_calls += 1
            self._budget.record_call(in_tok, out_tok, thoughts_tok)
        except _GeminiSkipError as exc:
            return self._fail_open_response(
                exc.status,
                total_calls,
                total_input_tokens,
                total_output_tokens,
                total_thoughts_tokens,
                extra=exc.extra if exc.extra else None,
            )

        # Distinguish evaluator failure (case 3) from legitimate empty result (case 2).
        # Case 2: successful parse returning [] — no verifiable claims, score = 1.0.
        # Case 3: JSONDecodeError, ValueError, or non-list JSON — evaluator failure,
        # fail-open with sub_reason "claim_extraction_parse_failure".
        try:
            _parsed_claims = json.loads(_strip_json_fences(claims_raw))
        except (json.JSONDecodeError, ValueError):
            _parsed_claims = None

        if not isinstance(_parsed_claims, list):
            return self._fail_open_response(
                "skipped_evaluator_error",
                total_calls,
                total_input_tokens,
                total_output_tokens,
                total_thoughts_tokens,
                extra={
                    "sub_reason": "claim_extraction_parse_failure",
                    "raw_response_snippet": claims_raw[:200],
                },
            )

        claims: list[str] = [str(c) for c in _parsed_claims]

        # Enforce claim cap
        claims = claims[:_MAX_CLAIMS]

        if not claims:
            # Case 2: Gemini returned [] — legitimate zero-claim answer
            return RailDecision(
                outcome="pass",
                reason="faithfulness: no claims to verify",
                details={
                    "faithfulness_status": "passed",
                    "score": 1.0,
                    "supported_claims": [],
                    "unsupported_claims": [],
                    "gemini_calls": total_calls,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "thoughts_tokens": total_thoughts_tokens,
                    "cost": self._budget.report(),
                },
            )

        # Step 2: per-claim NLI
        supported: list[str] = []
        unsupported: list[str] = []

        for claim in claims:
            verify_prompt = _CLAIM_VERIFICATION_PROMPT.format(
                context=context_text, claim=claim
            )
            try:
                projected = self._estimate_next_call_cost()
                ok, ceiling_reason = self._budget.can_proceed(projected)
                if not ok:
                    raise _GeminiSkipError("skipped_budget", {"ceiling": ceiling_reason})
                verdict_raw, in_tok, out_tok, thoughts_tok = await self._call_gemini(
                    verify_prompt, deadline
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                total_thoughts_tokens += thoughts_tok
                total_calls += 1
                self._budget.record_call(in_tok, out_tok, thoughts_tok)
            except _GeminiSkipError as exc:
                return self._fail_open_response(
                    exc.status,
                    total_calls,
                    total_input_tokens,
                    total_output_tokens,
                    total_thoughts_tokens,
                    partial_supported=supported,
                    partial_unsupported=unsupported,
                    extra=exc.extra if exc.extra else None,
                )

            # Distinguish verdict parse errors from ambiguous values from valid yes/no.
            # Case 1: valid dict with verdict "yes" or "no" — count normally.
            # Case 2: valid dict with ambiguous verdict value — fail-open, verdict_ambiguous.
            # Case 3: JSONDecodeError, ValueError, or non-dict JSON — fail-open, verdict_parse_failure.
            try:
                _vdata = json.loads(_strip_json_fences(verdict_raw))
            except (json.JSONDecodeError, ValueError):
                _vdata = None

            _verdict_error = None
            verdict = "no"

            if isinstance(_vdata, dict):
                _v = str(_vdata.get("verdict", "")).lower().strip()
                if _v in ("yes", "no"):
                    verdict = _v
                else:
                    _verdict_error = "verdict_ambiguous"
            else:
                _verdict_error = "verdict_parse_failure"

            if _verdict_error is not None:
                return self._fail_open_response(
                    "skipped_evaluator_error",
                    total_calls,
                    total_input_tokens,
                    total_output_tokens,
                    total_thoughts_tokens,
                    partial_supported=supported,
                    partial_unsupported=unsupported,
                    extra={"sub_reason": _verdict_error},
                )

            if verdict == "yes":
                supported.append(claim)
            else:
                unsupported.append(claim)

        # Step 3: compute score
        score = len(supported) / len(claims) if claims else 1.0

        base_details: dict[str, Any] = {
            "score": score,
            "threshold": self._threshold,
            "supported_claims": supported,
            "unsupported_claims": unsupported,
            "gemini_calls": total_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "thoughts_tokens": total_thoughts_tokens,
            "cost": self._budget.report(),
        }

        if score < self._threshold:
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

    def _fail_open_response(
        self,
        status: str,
        total_calls: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_thoughts_tokens: int,
        partial_supported: list[str] | None = None,
        partial_unsupported: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RailDecision:
        """Build a uniform fail-open RailDecision with accumulated telemetry.

        Routes all fail-open paths through a single shape so callers can rely
        on consistent keys (faithfulness_status, gemini_calls, cost, etc.).
        """
        details: dict[str, Any] = {
            "faithfulness_status": status,
            "gemini_calls": total_calls,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "thoughts_tokens": total_thoughts_tokens,
            "cost": self._budget.report(),
        }
        if partial_supported is not None:
            details["supported_claims_partial"] = partial_supported
            details["unsupported_claims_partial"] = partial_unsupported or []
            details["claims_verified_before_skip"] = (
                len(partial_supported) + len(partial_unsupported or [])
            )
        if extra:
            details.update(extra)
        return RailDecision(
            outcome="pass",
            reason=f"faithfulness fail-open: {status}",
            details=details,
        )

    def _estimate_next_call_cost(self) -> float:
        report = self._budget.report()
        count = report["call_count"]
        return report["run_total_usd"] / count if count > 0 else 0.001

    async def _call_gemini(
        self, prompt: str, deadline: float
    ) -> tuple[str, int, int, int]:
        """Call Gemini with per-call and total-budget timeouts.

        Returns (response_text, input_tokens, output_tokens, thoughts_tokens).
        Raises _GeminiSkipError on any failure that should fail-open.
        """
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _GeminiSkipError("skipped_timeout", {})

        timeout = min(self._per_call_timeout, remaining)
        try:
            result = await asyncio.wait_for(
                self._generate(prompt),
                timeout=timeout,
            )
            return result
        except _GeminiSkipError:
            raise
        except TimeoutError:
            raise _GeminiSkipError("skipped_timeout", {})
        except Exception as exc:
            return self._classify_gemini_error(exc)

    async def _generate(self, prompt: str) -> tuple[str, int, int, int]:
        """Async wrapper for the synchronous Gemini generate_content call."""
        from google.genai.errors import APIError, ClientError, ServerError

        def _sync_call() -> tuple[str, int, int, int]:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
            text = ""
            if response.candidates:
                first = response.candidates[0]
                if first.content and first.content.parts:
                    text = first.content.parts[0].text or ""
            usage = response.usage_metadata
            in_tok = usage.prompt_token_count or 0 if usage else 0
            out_tok = usage.candidates_token_count or 0 if usage else 0
            thoughts_tok = usage.thoughts_token_count or 0 if usage else 0
            return text, in_tok, out_tok, thoughts_tok

        try:
            return await asyncio.to_thread(_sync_call)
        except ClientError as exc:
            # 4xx from genai SDK: ClientError subclass of APIError
            code: int = getattr(exc, "code", 0)
            if code == 429:
                raise _GeminiSkipError("skipped_rate_limit", {}) from exc
            if code in {401, 403}:
                log.error("Gemini auth error — check GEMINI_API_KEY: %s", exc)
                raise _GeminiSkipError("skipped_auth_error", {}) from exc
            if "SAFETY" in str(exc).upper() or "BLOCKED" in str(exc).upper():
                raise _GeminiSkipError("skipped_safety_filter", {}) from exc
            raise _GeminiSkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc
        except ServerError as exc:
            raise _GeminiSkipError("skipped_upstream_error", {}) from exc
        except APIError as exc:
            if "SAFETY" in str(exc).upper() or "BLOCKED" in str(exc).upper():
                raise _GeminiSkipError("skipped_safety_filter", {}) from exc
            raise _GeminiSkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc

    def _classify_gemini_error(self, exc: Exception) -> tuple[str, int, int, int]:
        """Never called — exceptions are raised as _GeminiSkipError before reaching here."""
        raise _GeminiSkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc


class _GeminiSkipError(Exception):
    """Signal to fail-open. Carries a status string and extra details dict."""

    def __init__(self, status: str, extra: dict[str, Any]) -> None:
        self.status = status
        self.extra = extra
        super().__init__(status)
