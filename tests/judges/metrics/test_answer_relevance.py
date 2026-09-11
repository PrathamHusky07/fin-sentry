"""Tests for finsentry.judges.metrics.answer_relevance."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from finsentry.judges.metrics.answer_relevance import (
    ANSWER_RELEVANCE_PROMPT,
    AnswerRelevanceResult,
    evaluate_answer_relevance,
)
from finsentry.rails.output.cost_governance import CostBudget


def _budget() -> CostBudget:
    return CostBudget()


def _mock_gen(responses: list[tuple[str, int, int, int]]) -> AsyncMock:
    call_iter = iter(responses)

    async def _side(prompt: str) -> tuple[str, int, int, int]:
        return next(call_iter)

    return AsyncMock(side_effect=_side)


@pytest.mark.anyio
async def test_evaluate_answer_relevance_complete_high_score() -> None:
    """A clear, direct answer yields status=complete and score=1.0."""
    resp = json.dumps({"score": 1.0, "rationale": "Directly answers."})
    gen = _mock_gen([(resp, 100, 30, 0)])

    result = await evaluate_answer_relevance(
        question="What was Apple revenue in Q1 2024?",
        answer_text="Apple revenue in Q1 2024 was $119.6B.",
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert isinstance(result, AnswerRelevanceResult)
    assert result.status == "complete"
    assert result.score == 1.0
    assert result.rationale == "Directly answers."
    assert result.total_gemini_calls == 1


@pytest.mark.anyio
async def test_evaluate_answer_relevance_partial_score() -> None:
    """Score is propagated verbatim from judge response."""
    resp = json.dumps({"score": 0.7, "rationale": "Mostly addresses it."})
    gen = _mock_gen([(resp, 80, 25, 0)])

    result = await evaluate_answer_relevance(
        question="Explain Apple's growth drivers.",
        answer_text="iPhone and services drove growth.",
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "complete"
    assert result.score == 0.7


@pytest.mark.anyio
async def test_evaluate_answer_relevance_parse_failure_skips() -> None:
    """Malformed JSON response yields skipped_evaluator_error, fail-open."""
    gen = _mock_gen([("not json at all", 50, 10, 0)])

    result = await evaluate_answer_relevance(
        question="What is revenue?",
        answer_text="High revenue.",
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "skipped_evaluator_error"
    assert result.sub_reason == "parse_failure"
    assert result.raw_response_snippet is not None
    assert "not json at all" in result.raw_response_snippet


@pytest.mark.anyio
async def test_evaluate_answer_relevance_score_clamped_to_valid_range() -> None:
    """Score values outside [0, 1] are clamped rather than rejected."""
    resp = json.dumps({"score": 1.5, "rationale": "Overconfident judge."})
    gen = _mock_gen([(resp, 80, 25, 0)])

    result = await evaluate_answer_relevance(
        question="Q?",
        answer_text="A.",
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "complete"
    assert result.score == 1.0


@pytest.mark.anyio
async def test_evaluate_answer_relevance_budget_exhausted_skips() -> None:
    """Budget ceiling before first call yields skipped_budget."""
    budget = CostBudget(per_run_ceiling_usd=0.0)
    gen = _mock_gen([])  # should never be called

    result = await evaluate_answer_relevance(
        question="Q?",
        answer_text="A.",
        generate_fn=gen,
        cost_budget=budget,
    )

    assert result.status == "skipped_budget"
    gen.assert_not_called()


def test_answer_relevance_prompt_guards_verbosity_bias() -> None:
    """Prompt explicitly instructs not to reward length — verbosity bias guard."""
    assert "precision matters more than length" in ANSWER_RELEVANCE_PROMPT


def test_answer_relevance_prompt_guards_refusal_bias() -> None:
    """Prompt frames task as evaluation, not content generation — refusal bias guard."""
    assert "evaluating" in ANSWER_RELEVANCE_PROMPT.lower()
