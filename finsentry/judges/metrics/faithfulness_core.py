"""
Core Faithfulness evaluation logic (Es et al. 2023, RAGAS reference-free variant).

Shared by:
  - finsentry.rails.output.faithfulness.FaithfulnessRail (synchronous gateway rail)
  - finsentry.judges.flash_judge.FlashJudge (async evaluation consumer)

evaluate_faithfulness() accepts a generate_fn callable (prompt -> tuple) so
callers control the underlying API call. FaithfulnessRail passes self._generate
so tests can patch rail._generate without this module knowing about it.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from finsentry.rails.output.cost_governance import CostBudget

# ---------------------------------------------------------------------------
# Shared prompt constants (re-exported for FaithfulnessRail backward compat)
# ---------------------------------------------------------------------------

CLAIM_EXTRACTION_PROMPT = """\
Extract atomic factual claims from the following answer. Return ONLY a JSON array of \
strings, where each string is one atomic factual claim. Limit to at most 10 claims. \
If the answer contains no verifiable factual claims, return an empty array [].

Answer:
{answer}

Return only a JSON array of strings, no other text."""

CLAIM_VERIFICATION_PROMPT = """\
Given the following context, does the claim hold? Answer "yes" or "no" with a one-sentence \
rationale.

Context:
{context}

Claim: {claim}

Respond in this exact JSON format:
{{"verdict": "yes" or "no", "rationale": "one sentence"}}"""

_MAX_CLAIMS = 10
_PER_CALL_TIMEOUT = 30.0
_TOTAL_BUDGET = 120.0

# Type alias for the raw generate callable.
GenerateFn = Callable[[str], Awaitable[tuple[str, int, int, int]]]

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class FaithfulnessResult:
    score: float
    supported_claims: list[str]
    unsupported_claims: list[str]
    total_gemini_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_thoughts_tokens: int
    status: Literal[
        "complete",
        "skipped_evaluator_error",
        "skipped_rate_limit",
        "skipped_timeout",
        "skipped_budget",
        "skipped_upstream_error",
        "skipped_safety_filter",
        "skipped_auth_error",
        "skipped_no_key",
    ]
    sub_reason: str | None = None
    partial_supported: list[str] | None = None
    partial_unsupported: list[str] | None = None
    raw_response_snippet: str | None = None
    cost_report: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal skip signal
# ---------------------------------------------------------------------------


class _SkipError(Exception):
    """Signal to fail-open. Carries a status string and extra details dict."""

    def __init__(self, status: str, extra: dict[str, Any]) -> None:
        self.status = status
        self.extra = extra
        super().__init__(status)


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences that Gemini may wrap around JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


async def evaluate_faithfulness(
    answer_text: str,
    chunk_texts: list[str],
    generate_fn: GenerateFn,
    cost_budget: CostBudget,
    per_call_timeout: float = _PER_CALL_TIMEOUT,
    total_budget: float = _TOTAL_BUDGET,
) -> FaithfulnessResult:
    """Run Es et al. 2023 reference-free Faithfulness on (answer, chunks).

    generate_fn: async callable (prompt: str) -> (text, in_tok, out_tok, thoughts_tok).
    The caller is responsible for constructing this from their Gemini client. All
    Gemini errors should be raised as _SkipError so they produce a skipped_* status.

    Returns a FaithfulnessResult. Never raises (all error paths produce skipped_* status).
    """
    deadline = time.monotonic() + total_budget
    total_input_tokens = 0
    total_output_tokens = 0
    total_thoughts_tokens = 0
    total_calls = 0

    context_text = "\n\n".join(chunk_texts)

    def _build_result(
        status: str,
        score: float = 0.0,
        supported: list[str] | None = None,
        unsupported: list[str] | None = None,
        sub_reason: str | None = None,
        partial_supported: list[str] | None = None,
        partial_unsupported: list[str] | None = None,
        raw_response_snippet: str | None = None,
    ) -> FaithfulnessResult:
        return FaithfulnessResult(
            score=score,
            supported_claims=supported or [],
            unsupported_claims=unsupported or [],
            total_gemini_calls=total_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_thoughts_tokens=total_thoughts_tokens,
            status=status,  # type: ignore[arg-type]
            sub_reason=sub_reason,
            partial_supported=partial_supported,
            partial_unsupported=partial_unsupported,
            raw_response_snippet=raw_response_snippet,
            cost_report=cost_budget.report(),
        )

    # Step 1: claim extraction
    extract_prompt = CLAIM_EXTRACTION_PROMPT.format(answer=answer_text)
    try:
        projected = _estimate_cost(cost_budget)
        ok, ceiling_reason = cost_budget.can_proceed(projected)
        if not ok:
            raise _SkipError("skipped_budget", {"ceiling": ceiling_reason})
        claims_raw, in_tok, out_tok, thoughts_tok = await _call_with_timeout(
            generate_fn, extract_prompt, deadline, per_call_timeout
        )
        total_input_tokens += in_tok
        total_output_tokens += out_tok
        total_thoughts_tokens += thoughts_tok
        total_calls += 1
        cost_budget.record_call(in_tok, out_tok, thoughts_tok)
    except _SkipError as exc:
        return _build_result(exc.status, sub_reason=exc.extra.get("ceiling"))

    try:
        _parsed_claims = json.loads(_strip_json_fences(claims_raw))
    except (json.JSONDecodeError, ValueError):
        _parsed_claims = None

    if not isinstance(_parsed_claims, list):
        return _build_result(
            "skipped_evaluator_error",
            sub_reason="claim_extraction_parse_failure",
            raw_response_snippet=claims_raw[:200],
        )

    claims: list[str] = [str(c) for c in _parsed_claims][:_MAX_CLAIMS]

    if not claims:
        return _build_result("complete", score=1.0, supported=[], unsupported=[])

    # Step 2: per-claim NLI
    supported: list[str] = []
    unsupported: list[str] = []

    for claim in claims:
        verify_prompt = CLAIM_VERIFICATION_PROMPT.format(
            context=context_text, claim=claim
        )
        try:
            projected = _estimate_cost(cost_budget)
            ok, ceiling_reason = cost_budget.can_proceed(projected)
            if not ok:
                raise _SkipError("skipped_budget", {"ceiling": ceiling_reason})
            verdict_raw, in_tok, out_tok, thoughts_tok = await _call_with_timeout(
                generate_fn, verify_prompt, deadline, per_call_timeout
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_thoughts_tokens += thoughts_tok
            total_calls += 1
            cost_budget.record_call(in_tok, out_tok, thoughts_tok)
        except _SkipError as exc:
            return _build_result(
                exc.status,
                partial_supported=list(supported),
                partial_unsupported=list(unsupported),
                sub_reason=exc.extra.get("ceiling"),
            )

        try:
            _vdata = json.loads(_strip_json_fences(verdict_raw))
        except (json.JSONDecodeError, ValueError):
            _vdata = None

        verdict_error = None
        verdict = "no"

        if isinstance(_vdata, dict):
            _v = str(_vdata.get("verdict", "")).lower().strip()
            if _v in ("yes", "no"):
                verdict = _v
            else:
                verdict_error = "verdict_ambiguous"
        else:
            verdict_error = "verdict_parse_failure"

        if verdict_error is not None:
            return _build_result(
                "skipped_evaluator_error",
                partial_supported=list(supported),
                partial_unsupported=list(unsupported),
                sub_reason=verdict_error,
            )

        if verdict == "yes":
            supported.append(claim)
        else:
            unsupported.append(claim)

    score = len(supported) / len(claims) if claims else 1.0
    return _build_result("complete", score=score, supported=supported, unsupported=unsupported)


# ---------------------------------------------------------------------------
# Timeout wrapper
# ---------------------------------------------------------------------------


async def _call_with_timeout(
    generate_fn: GenerateFn,
    prompt: str,
    deadline: float,
    per_call_timeout: float,
) -> tuple[str, int, int, int]:
    """Apply per-call and total-budget timeouts around generate_fn."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _SkipError("skipped_timeout", {})

    timeout = min(per_call_timeout, remaining)
    try:
        result = await asyncio.wait_for(generate_fn(prompt), timeout=timeout)
        return result
    except _SkipError:
        raise
    except TimeoutError:
        raise _SkipError("skipped_timeout", {})


# ---------------------------------------------------------------------------
# Estimate cost helper
# ---------------------------------------------------------------------------


def _estimate_cost(budget: CostBudget) -> float:
    report = budget.report()
    count = report["call_count"]
    return report["run_total_usd"] / count if count > 0 else 0.001


# ---------------------------------------------------------------------------
# Gemini generate function factory — for use by FlashJudge
# ---------------------------------------------------------------------------


def make_gemini_generate_fn(
    client: Any,
    model_name: str,
) -> GenerateFn:
    """Build a GenerateFn that calls the Gemini API and raises _SkipError on failure."""
    import logging

    log = logging.getLogger(__name__)

    async def _generate(prompt: str) -> tuple[str, int, int, int]:
        from google.genai.errors import APIError, ClientError, ServerError

        def _sync_call() -> tuple[str, int, int, int]:
            response = client.models.generate_content(
                model=model_name,
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
            code: int = getattr(exc, "code", 0)
            if code == 429:
                raise _SkipError("skipped_rate_limit", {}) from exc
            if code in {401, 403}:
                log.error("Gemini auth error — check credentials: %s", exc)
                raise _SkipError("skipped_auth_error", {}) from exc
            if "SAFETY" in str(exc).upper() or "BLOCKED" in str(exc).upper():
                raise _SkipError("skipped_safety_filter", {}) from exc
            raise _SkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc
        except ServerError as exc:
            raise _SkipError("skipped_upstream_error", {}) from exc
        except APIError as exc:
            if "SAFETY" in str(exc).upper() or "BLOCKED" in str(exc).upper():
                raise _SkipError("skipped_safety_filter", {}) from exc
            raise _SkipError("skipped_upstream_error", {"error_detail": str(exc)}) from exc

    return _generate
