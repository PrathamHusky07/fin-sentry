"""
Answer Relevance metric (Zheng et al. 2023 bias mitigations applied).

Measures: does the answer directly address the question?

Zheng et al. identified four judge biases this module guards against:
  1. Position bias: the judge may prefer the first option in a comparison.
     Mitigation: single-answer scoring (no pairwise comparison).
  2. Verbosity bias: the judge may favor longer answers regardless of quality.
     Mitigation: prompt explicitly instructs to not reward length over precision.
  3. Self-enhancement bias: a model judging its own output inflates scores.
     Mitigation: cross-model judging (FlashJudge uses Gemini; gateway uses
     different model than the RAG LLM).
  4. Refusal bias: the judge may refuse to score sensitive financial content.
     Mitigation: framing the task as an evaluation role, not content generation.

Reference: Es et al. 2023 (RAGAS) for the metric definition;
           Zheng et al. 2023 (MT-Bench / Chatbot Arena) for bias taxonomy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from finsentry.judges.metrics.faithfulness_core import (
    GenerateFn,
    _call_with_timeout,
    _estimate_cost,
    _SkipError,
    _strip_json_fences,
)
from finsentry.rails.output.cost_governance import CostBudget

# ---------------------------------------------------------------------------
# Prompt (single, no pairwise — guards position bias and verbosity bias)
# ---------------------------------------------------------------------------

ANSWER_RELEVANCE_PROMPT = """\
You are evaluating the relevance of an AI assistant's answer to the user's question.
Your task is to score how directly and completely the answer addresses the question.
Do not reward answers that are longer or more elaborate — precision matters more than length.
Do not penalize answers that refuse to speculate beyond available evidence.

Question: {question}

Answer: {answer}

Score the answer on a scale from 0.0 to 1.0:
  1.0 — Directly and completely answers the question.
  0.7 — Mostly answers the question with minor omissions.
  0.4 — Partially answers the question; key parts are missing or off-topic.
  0.0 — Does not answer the question or is completely off-topic.

Respond in this exact JSON format (no other text):
{{"score": <float 0.0-1.0>, "rationale": "<one sentence>"}}"""

_PER_CALL_TIMEOUT = 30.0
_TOTAL_BUDGET = 60.0


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class AnswerRelevanceResult:
    score: float
    rationale: str
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
    raw_response_snippet: str | None = None
    cost_report: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


async def evaluate_answer_relevance(
    question: str,
    answer_text: str,
    generate_fn: GenerateFn,
    cost_budget: CostBudget,
    per_call_timeout: float = _PER_CALL_TIMEOUT,
    total_budget: float = _TOTAL_BUDGET,
) -> AnswerRelevanceResult:
    """Score whether answer_text directly addresses question.

    Returns AnswerRelevanceResult. Never raises.
    """
    import time

    deadline = time.monotonic() + total_budget
    total_input_tokens = 0
    total_output_tokens = 0
    total_thoughts_tokens = 0
    total_calls = 0

    def _build_result(
        status: str,
        score: float = 0.0,
        rationale: str = "",
        sub_reason: str | None = None,
        raw_response_snippet: str | None = None,
    ) -> AnswerRelevanceResult:
        return AnswerRelevanceResult(
            score=score,
            rationale=rationale,
            total_gemini_calls=total_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_thoughts_tokens=total_thoughts_tokens,
            status=status,  # type: ignore[arg-type]
            sub_reason=sub_reason,
            raw_response_snippet=raw_response_snippet,
            cost_report=cost_budget.report(),
        )

    prompt = ANSWER_RELEVANCE_PROMPT.format(question=question, answer=answer_text)

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
        return _build_result(exc.status, sub_reason=exc.extra.get("ceiling"))

    try:
        data = json.loads(_strip_json_fences(raw))
    except (json.JSONDecodeError, ValueError):
        return _build_result(
            "skipped_evaluator_error",
            sub_reason="parse_failure",
            raw_response_snippet=raw[:200],
        )

    if not isinstance(data, dict):
        return _build_result(
            "skipped_evaluator_error",
            sub_reason="parse_failure",
            raw_response_snippet=raw[:200],
        )

    raw_score = data.get("score")
    try:
        score = float(raw_score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _build_result(
            "skipped_evaluator_error",
            sub_reason="score_missing_or_invalid",
            raw_response_snippet=raw[:200],
        )

    if not (0.0 <= score <= 1.0):
        score = max(0.0, min(1.0, score))

    rationale = str(data.get("rationale", ""))
    return _build_result("complete", score=score, rationale=rationale)
