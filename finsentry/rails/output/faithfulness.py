"""
Reference-free Faithfulness rail: measures whether the generated answer's
factual claims are supported by the retrieved context.

Methodology: Es et al. 2023 (RAGAS paper), reference-free variant.
  1. Claim extraction: prompt Gemini to extract atomic factual claims from answer.
  2. Per-claim NLI: for each claim, prompt Gemini to verify against context.
  3. Score: supported_claims / total_claims (1.0 when total_claims == 0).

This is our own implementation of the RAGAS Faithfulness metric using the
google-genai SDK directly. The ragas PyPI package was evaluated and rejected
because it carries hard dependencies on openai>=1.0.0 and langchain_openai,
which violate the project's zero-cost constraint. See ADR 005.

Failure policy (consistent with ADR 004 taxonomy and config/rails.yml):
  - API key absent: skip (rail disabled at init).
  - 429 RESOURCE_EXHAUSTED: fail-open, status skipped_rate_limit. Do not retry.
  - Timeout (per-call 8s, total budget 20s): fail-open, skipped_timeout.
  - 500/502/503 from Gemini: fail-open, skipped_upstream_error.
  - Safety filter rejection: fail-open, skipped_safety_filter.
  - 403/401 auth error: fail-open + ERROR log (config bug worth investigating).
  - All fail-open paths annotate output_rail_trace with faithfulness_status.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from finsentry.rails.base import RailDecision

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
            return RailDecision(
                outcome="pass",
                reason="faithfulness rail disabled (no api key)",
                details={"faithfulness_status": "skipped_no_key"},
            )

        deadline = time.monotonic() + _TOTAL_BUDGET
        total_input_tokens = 0
        total_output_tokens = 0
        total_calls = 0

        context_text = "\n\n".join(
            f"[chunk_id={getattr(c, 'chunk_id', '')}] {getattr(c, 'text', '')}"
            for c in retrieved_chunks
        )

        # Step 1: claim extraction
        extract_prompt = _CLAIM_EXTRACTION_PROMPT.format(answer=answer_text)
        try:
            claims_raw, in_tok, out_tok = await self._call_gemini(
                extract_prompt, deadline
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_calls += 1
        except _GeminiSkipError as exc:
            return RailDecision(
                outcome="pass",
                reason=f"faithfulness skipped: {exc.status}",
                details={"faithfulness_status": exc.status, **exc.extra},
            )

        try:
            claims: list[str] = json.loads(_strip_json_fences(claims_raw))
            if not isinstance(claims, list):
                claims = []
        except (json.JSONDecodeError, ValueError):
            claims = []

        # Enforce claim cap
        claims = claims[:_MAX_CLAIMS]

        if not claims:
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
                verdict_raw, in_tok, out_tok = await self._call_gemini(
                    verify_prompt, deadline
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                total_calls += 1
            except _GeminiSkipError as exc:
                return RailDecision(
                    outcome="pass",
                    reason=f"faithfulness skipped mid-verification: {exc.status}",
                    details={
                        "faithfulness_status": exc.status,
                        "claims_verified_before_skip": len(supported) + len(unsupported),
                        **exc.extra,
                    },
                )

            verdict = "no"
            try:
                verdict_data = json.loads(_strip_json_fences(verdict_raw))
                if isinstance(verdict_data, dict):
                    verdict = str(verdict_data.get("verdict", "no")).lower().strip()
            except (json.JSONDecodeError, ValueError):
                verdict = "no"

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

    async def _call_gemini(
        self, prompt: str, deadline: float
    ) -> tuple[str, int, int]:
        """Call Gemini with per-call and total-budget timeouts.

        Returns (response_text, input_tokens, output_tokens).
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

    async def _generate(self, prompt: str) -> tuple[str, int, int]:
        """Async wrapper for the synchronous Gemini generate_content call."""
        from google.genai.errors import APIError, ClientError, ServerError

        def _sync_call() -> tuple[str, int, int]:
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
            return text, in_tok, out_tok

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

    def _classify_gemini_error(self, exc: Exception) -> tuple[str, int, int]:
        """Never called — exceptions are raised as _GeminiSkipError before reaching here."""
        raise _GeminiSkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc


class _GeminiSkipError(Exception):
    """Signal to fail-open. Carries a status string and extra details dict."""

    def __init__(self, status: str, extra: dict[str, Any]) -> None:
        self.status = status
        self.extra = extra
        super().__init__(status)
