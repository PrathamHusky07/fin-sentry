"""Tests for finsentry.judges.metrics.context_relevance."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from finsentry.judges.metrics.context_relevance import (
    CONTEXT_RELEVANCE_PROMPT,
    ContextRelevanceResult,
    evaluate_context_relevance,
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
async def test_evaluate_context_relevance_single_relevant_chunk() -> None:
    """One relevant chunk yields score=1.0 and one chunk_score."""
    resp = json.dumps({"score": 1.0, "rationale": "Directly relevant."})
    gen = _mock_gen([(resp, 100, 30, 0)])

    result = await evaluate_context_relevance(
        question="What was Apple revenue?",
        chunk_texts=["Apple Q1 2024 revenue was $119.6B."],
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert isinstance(result, ContextRelevanceResult)
    assert result.status == "complete"
    assert result.score == 1.0
    assert result.chunk_scores == [1.0]
    assert len(result.chunk_rationales) == 1


@pytest.mark.anyio
async def test_evaluate_context_relevance_mean_of_chunk_scores() -> None:
    """Overall score is the mean of per-chunk scores."""
    resps = [
        (json.dumps({"score": 1.0, "rationale": "Relevant."}), 80, 25, 0),
        (json.dumps({"score": 0.4, "rationale": "Partially relevant."}), 80, 25, 0),
    ]
    gen = _mock_gen(resps)

    result = await evaluate_context_relevance(
        question="What is Apple revenue?",
        chunk_texts=["Apple revenue chunk.", "Off-topic chunk."],
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "complete"
    assert abs(result.score - 0.7) < 1e-9
    assert result.chunk_scores == [1.0, 0.4]


@pytest.mark.anyio
async def test_evaluate_context_relevance_empty_chunks_returns_zero() -> None:
    """Empty chunk list returns score=0.0 with no Gemini calls."""
    gen = _mock_gen([])

    result = await evaluate_context_relevance(
        question="Q?",
        chunk_texts=[],
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "complete"
    assert result.score == 0.0
    assert result.total_gemini_calls == 0
    gen.assert_not_called()


@pytest.mark.anyio
async def test_evaluate_context_relevance_parse_failure_skips() -> None:
    """Malformed response on first chunk yields skipped_evaluator_error."""
    gen = _mock_gen([("not valid json", 50, 10, 0)])

    result = await evaluate_context_relevance(
        question="Q?",
        chunk_texts=["Some chunk."],
        generate_fn=gen,
        cost_budget=_budget(),
    )

    assert result.status == "skipped_evaluator_error"
    assert result.sub_reason == "parse_failure"
    assert result.raw_response_snippet is not None


@pytest.mark.anyio
async def test_evaluate_context_relevance_partial_scores_on_budget_exhaustion() -> None:
    """If budget runs out mid-evaluation, partial_chunk_scores holds completed scores."""
    from finsentry.judges.metrics.faithfulness_core import _SkipError

    first_resp = json.dumps({"score": 0.8, "rationale": "Good."})
    call_count = 0

    async def _gen(prompt: str) -> tuple[str, int, int, int]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return first_resp, 80, 25, 0
        raise _SkipError("skipped_budget", {})

    result = await evaluate_context_relevance(
        question="Q?",
        chunk_texts=["Chunk A.", "Chunk B."],
        generate_fn=_gen,
        cost_budget=_budget(),
    )

    # First chunk scored, second raised budget skip
    assert result.status == "skipped_budget"
    assert result.partial_chunk_scores is not None
    assert len(result.partial_chunk_scores) == 1
    assert abs(result.partial_chunk_scores[0] - 0.8) < 1e-9


def test_context_relevance_prompt_scores_per_chunk() -> None:
    """Prompt operates on a single passage — guards position bias (no pairwise ranking)."""
    assert "Retrieved passage" in CONTEXT_RELEVANCE_PROMPT
    # No mention of comparing multiple passages
    assert "compare" not in CONTEXT_RELEVANCE_PROMPT.lower()


def test_context_relevance_prompt_guards_verbosity_bias() -> None:
    """Prompt explicitly discourages rewarding longer passages."""
    assert "longer" in CONTEXT_RELEVANCE_PROMPT.lower()
