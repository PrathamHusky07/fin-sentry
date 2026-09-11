"""
Context Relevance metric (Zheng et al. 2023 bias mitigations applied).

Measures: does the retrieved context actually contain information needed
to answer the question? High context relevance means retrieval is precise.
Low context relevance means the vector search returned off-topic chunks.

Zheng et al. bias mitigations (same four as answer_relevance.py):
  1. Position bias: prompt scores each chunk independently (no ranking).
  2. Verbosity bias: longer chunks are not scored higher; precision counts.
  3. Self-enhancement bias: cross-model judging (Gemini judges, not the RAG LLM).
  4. Refusal bias: evaluation framing, not content-generation framing.

The overall context relevance score is the mean of per-chunk scores so that
adding irrelevant chunks degrades the metric — reflecting the precision goal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from finsentry.judges.metrics.faithfulness_core import (
    GenerateFn,
    _SkipError,
    _call_with_timeout,
    _estimate_cost,
    _strip_json_fences,
)
from finsentry.rails.output.cost_governance import CostBudget

# ---------------------------------------------------------------------------
# Prompt (per-chunk, independent scoring — guards position bias)
# ---------------------------------------------------------------------------

CONTEXT_RELEVANCE_PROMPT = """\
You are evaluating whether a retrieved text passage contains information useful \
for answering the user's question.
Do not favor longer passages — a short but precise passage scores higher than \
a long off-topic one.
Do not penalize passages that discuss the topic without directly answering the question.

Question: {question}

Retrieved passage:
{chunk_text}

Score the passage on a scale from 0.0 to 1.0:
  1.0 — The passage directly contains information needed to answer the question.
  0.7 — The passage is related and partially useful.
  0.4 — The passage is on the general topic but not specifically useful.
  0.0 — The passage is unrelated to the question.

Respond in this exact JSON format (no other text):
{{"score": <float 0.0-1.0>, "rationale": "<one sentence>"}}"""

_PER_CALL_TIMEOUT = 30.0
_TOTAL_BUDGET = 120.0
_MAX_CHUNKS = 10


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ContextRelevanceResult:
    score: float
    chunk_scores: list[float]
    chunk_rationales: list[str]
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
    partial_chunk_scores: list[float] | None = None
    raw_response_snippet: str | None = None
    cost_report: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


async def evaluate_context_relevance(
    question: str,
    chunk_texts: list[str],
    generate_fn: GenerateFn,
    cost_budget: CostBudget,
    per_call_timeout: float = _PER_CALL_TIMEOUT,
    total_budget: float = _TOTAL_BUDGET,
) -> ContextRelevanceResult:
    """Score how relevant each retrieved chunk is to the question.

    Returns ContextRelevanceResult. Never raises.
    Overall score = mean of per-chunk scores (penalizes irrelevant chunks).
    """
    import time

    deadline = time.monotonic() + total_budget
    total_input_tokens = 0
    total_output_tokens = 0
    total_thoughts_tokens = 0
    total_calls = 0

    chunks = chunk_texts[:_MAX_CHUNKS]
    chunk_scores: list[float] = []
    chunk_rationales: list[str] = []

    def _build_result(
        status: str,
        score: float = 0.0,
        sub_reason: str | None = None,
        partial_chunk_scores: list[float] | None = None,
        raw_response_snippet: str | None = None,
    ) -> ContextRelevanceResult:
        return ContextRelevanceResult(
            score=score,
            chunk_scores=list(chunk_scores),
            chunk_rationales=list(chunk_rationales),
            total_gemini_calls=total_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_thoughts_tokens=total_thoughts_tokens,
            status=status,  # type: ignore[arg-type]
            sub_reason=sub_reason,
            partial_chunk_scores=partial_chunk_scores,
            raw_response_snippet=raw_response_snippet,
            cost_report=cost_budget.report(),
        )

    if not chunks:
        return _build_result("complete", score=0.0)

    for chunk_text in chunks:
        prompt = CONTEXT_RELEVANCE_PROMPT.format(question=question, chunk_text=chunk_text)

        try:
            projected = _estimate_cost(cost_budget)
            ok, ceiling_reason = cost_budget.can_proceed(projected)
            if not ok:
                raise _SkipError("skipped_budget", {"ceiling": ceiling_reason})
            raw, in_tok, out_tok, thoughts_tok = await _call_with_timeout(
                generate_fn, prompt, deadline, per_call_timeout
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_thoughts_tokens += thoughts_tok
            total_calls += 1
            cost_budget.record_call(in_tok, out_tok, thoughts_tok)
        except _SkipError as exc:
            return _build_result(
                exc.status,
                sub_reason=exc.extra.get("ceiling"),
                partial_chunk_scores=list(chunk_scores),
            )

        try:
            data = json.loads(_strip_json_fences(raw))
        except (json.JSONDecodeError, ValueError):
            return _build_result(
                "skipped_evaluator_error",
                sub_reason="parse_failure",
                partial_chunk_scores=list(chunk_scores),
                raw_response_snippet=raw[:200],
            )

        if not isinstance(data, dict):
            return _build_result(
                "skipped_evaluator_error",
                sub_reason="parse_failure",
                partial_chunk_scores=list(chunk_scores),
                raw_response_snippet=raw[:200],
            )

        raw_score = data.get("score")
        try:
            chunk_score = float(raw_score)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _build_result(
                "skipped_evaluator_error",
                sub_reason="score_missing_or_invalid",
                partial_chunk_scores=list(chunk_scores),
                raw_response_snippet=raw[:200],
            )

        chunk_score = max(0.0, min(1.0, chunk_score))
        chunk_scores.append(chunk_score)
        chunk_rationales.append(str(data.get("rationale", "")))

    overall = sum(chunk_scores) / len(chunk_scores) if chunk_scores else 0.0
    return _build_result("complete", score=overall)
