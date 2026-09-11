"""Tests for finsentry.judges.metrics.faithfulness_core.

Verifies that the shared metric core produces correct results and that
FaithfulnessRail uses the same prompts as the core (ensuring FlashJudge
and the gateway rail score identically for the same input).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from finsentry.judges.metrics.faithfulness_core import (
    CLAIM_EXTRACTION_PROMPT,
    CLAIM_VERIFICATION_PROMPT,
    FaithfulnessResult,
    evaluate_faithfulness,
)
from finsentry.rails.output.cost_governance import CostBudget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_budget() -> CostBudget:
    return CostBudget()


def _mock_generate(responses: list[tuple[str, int, int, int]]) -> AsyncMock:
    """AsyncMock that yields successive (text, in_tok, out_tok, thoughts_tok) tuples."""
    call_iter = iter(responses)

    async def _side_effect(prompt: str) -> tuple[str, int, int, int]:
        return next(call_iter)

    mock = AsyncMock(side_effect=_side_effect)
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_evaluate_faithfulness_returns_score_and_supported_claims_on_success() -> None:
    """Happy path: all claims supported, score=1.0, status=complete."""
    claims_json = json.dumps(["Apple had record revenue.", "iPhone led growth."])
    verdict_yes = json.dumps({"verdict": "yes", "rationale": "confirmed"})
    responses = [
        (claims_json, 100, 30, 10),
        (verdict_yes, 50, 20, 5),
        (verdict_yes, 50, 20, 5),
    ]
    generate_fn = _mock_generate(responses)

    result = await evaluate_faithfulness(
        answer_text="Apple had record revenue. iPhone led growth.",
        chunk_texts=["Apple revenue was $94.9B. iPhone sales drove growth."],
        generate_fn=generate_fn,
        cost_budget=_make_budget(),
    )

    assert isinstance(result, FaithfulnessResult)
    assert result.status == "complete"
    assert result.score == 1.0
    assert len(result.supported_claims) == 2
    assert len(result.unsupported_claims) == 0
    assert result.total_gemini_calls == 3


@pytest.mark.anyio
async def test_evaluate_faithfulness_returns_status_skipped_on_evaluator_error() -> None:
    """Malformed claim extraction -> skipped_evaluator_error, fail-open."""
    generate_fn = _mock_generate([("not valid json", 50, 10, 0)])

    result = await evaluate_faithfulness(
        answer_text="Some answer.",
        chunk_texts=["Some context."],
        generate_fn=generate_fn,
        cost_budget=_make_budget(),
    )

    assert result.status == "skipped_evaluator_error"
    assert result.sub_reason == "claim_extraction_parse_failure"
    assert result.raw_response_snippet is not None
    assert "not valid json" in result.raw_response_snippet


@pytest.mark.anyio
async def test_evaluate_faithfulness_reuses_same_prompts_as_rail() -> None:
    """The prompts used by evaluate_faithfulness match the FaithfulnessRail prompts.

    This ensures that FlashJudge (which calls evaluate_faithfulness directly) and
    the gateway FaithfulnessRail produce scores from identical methodology.
    """
    captured_prompts: list[str] = []

    async def _capture(prompt: str) -> tuple[str, int, int, int]:
        captured_prompts.append(prompt)
        if len(captured_prompts) == 1:
            return (json.dumps(["One claim."]), 50, 20, 0)
        return (json.dumps({"verdict": "yes", "rationale": "ok"}), 50, 20, 0)

    await evaluate_faithfulness(
        answer_text="One claim.",
        chunk_texts=["Context text."],
        generate_fn=_capture,
        cost_budget=_make_budget(),
    )

    assert len(captured_prompts) == 2

    # Extraction prompt must contain the prompt template structure
    assert "Extract atomic factual claims" in captured_prompts[0]
    assert "One claim." in captured_prompts[0]

    # Verification prompt must contain the claim and context
    assert "Context text." in captured_prompts[1]
    assert "One claim." in captured_prompts[1]

    # The exact same prompt constants are used (not copies)
    from finsentry.rails.output.faithfulness import (
        _CLAIM_EXTRACTION_PROMPT,
        _CLAIM_VERIFICATION_PROMPT,
    )

    assert _CLAIM_EXTRACTION_PROMPT is CLAIM_EXTRACTION_PROMPT
    assert _CLAIM_VERIFICATION_PROMPT is CLAIM_VERIFICATION_PROMPT
