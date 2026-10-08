"""Tests for CostBudget cost governance layer."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from finsentry.rails.output.cost_governance import (
    _INPUT_USD_PER_M_TOKENS,
    _OUTPUT_USD_PER_M_TOKENS,
    CostBudget,
)
from finsentry.rails.output.faithfulness import FaithfulnessRail

# ---------------------------------------------------------------------------
# CostBudget unit tests
# ---------------------------------------------------------------------------


def test_estimate_call_cost_uses_output_rate_for_thinking_tokens() -> None:
    # 100 input, 50 output, 200 thinking
    cost = CostBudget.estimate_call_cost(
        prompt_tokens=100, candidates_tokens=50, thoughts_tokens=200
    )
    expected_input = 100 / 1_000_000 * _INPUT_USD_PER_M_TOKENS
    expected_output = (50 + 200) / 1_000_000 * _OUTPUT_USD_PER_M_TOKENS
    assert abs(cost - (expected_input + expected_output)) < 1e-9


def test_per_call_ceiling_blocks_expensive_projection() -> None:
    budget = CostBudget(per_call_ceiling_usd=0.01)
    allowed, reason = budget.can_proceed(projected_call_cost_usd=0.02)
    assert not allowed
    assert reason == "per_call_ceiling_exceeded"


def test_per_run_ceiling_accumulates_across_calls() -> None:
    budget = CostBudget(per_run_ceiling_usd=0.005)
    budget.record_call(prompt_tokens=1000, candidates_tokens=500, thoughts_tokens=200)
    # After one call, run total > 0; project another call that would exceed ceiling
    allowed, reason = budget.can_proceed(projected_call_cost_usd=0.005)
    assert not allowed
    assert reason == "per_run_ceiling_exceeded"


def test_per_day_ceiling_accumulates_across_calls() -> None:
    budget = CostBudget(per_day_ceiling_usd=0.001)
    budget.record_call(prompt_tokens=500, candidates_tokens=200, thoughts_tokens=100)
    allowed, reason = budget.can_proceed(projected_call_cost_usd=0.001)
    assert not allowed
    assert reason == "per_day_ceiling_exceeded"


def test_report_totals_include_thinking_tokens() -> None:
    budget = CostBudget()
    budget.record_call(prompt_tokens=100, candidates_tokens=50, thoughts_tokens=200)
    budget.record_call(prompt_tokens=80, candidates_tokens=30, thoughts_tokens=150)
    report = budget.report()
    assert report["prompt_tokens_total"] == 180
    assert report["candidates_tokens_total"] == 80
    assert report["thoughts_tokens_total"] == 350
    assert report["call_count"] == 2
    assert report["run_total_usd"] > 0
    assert report["day_total_usd"] == report["run_total_usd"]


def test_can_proceed_returns_ok_when_under_all_ceilings() -> None:
    budget = CostBudget(per_call_ceiling_usd=0.05, per_run_ceiling_usd=1.0, per_day_ceiling_usd=5.0)
    allowed, reason = budget.can_proceed(projected_call_cost_usd=0.01)
    assert allowed
    assert reason == "ok"


# ---------------------------------------------------------------------------
# FaithfulnessRail integration tests for budget
# ---------------------------------------------------------------------------


def _make_rail_with_tight_budget(
    per_call_usd: float = 0.02,
    per_run_usd: float = 5.0,
    per_day_usd: float = 25.0,
) -> FaithfulnessRail:
    from finsentry.rails.output.cost_governance import CostBudget

    rail = FaithfulnessRail.__new__(FaithfulnessRail)
    rail._model_name = "gemini-3.6-flash"
    rail._threshold = 0.7
    rail._per_call_timeout = 8.0
    rail._enabled = True
    rail._mode = "developer"
    rail._client = MagicMock()
    rail._budget_factory = lambda: CostBudget(
        per_call_ceiling_usd=per_call_usd,
        per_run_ceiling_usd=per_run_usd,
        per_day_ceiling_usd=per_day_usd,
    )
    return rail


def _make_chunk(chunk_id: str, text: str = "Revenue was $94.9B.") -> Any:
    c = MagicMock()
    c.chunk_id = chunk_id
    c.text = text
    return c


@pytest.mark.asyncio
async def test_faithfulness_rail_blocks_on_budget_ceiling_with_skipped_budget_status() -> None:
    # Set per_run_ceiling so low that even first call would exceed it after projection
    rail = _make_rail_with_tight_budget(per_run_usd=0.0)
    decision = await rail.check("Some answer.", [_make_chunk("c1")])
    # Budget check fires before Gemini call; rail fails open
    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_budget"
    assert "ceiling" in decision.details


@pytest.mark.asyncio
async def test_faithfulness_rail_records_thinking_tokens_from_usage_metadata() -> None:

    rail = _make_rail_with_tight_budget()

    async def _gen_with_thoughts(prompt: str) -> tuple[str, int, int, int]:
        if "Extract atomic" in prompt:
            return (json.dumps(["Single claim."]), 100, 30, 90)
        return (json.dumps({"verdict": "yes", "rationale": "ok"}), 50, 20, 45)

    with patch.object(rail, "_generate", side_effect=_gen_with_thoughts):
        decision = await rail.check("Single claim.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["thoughts_tokens"] == 90 + 45
    cost = decision.details["cost"]
    assert cost["thoughts_tokens_total"] == 90 + 45
    assert cost["call_count"] == 2
    # Thinking tokens billed at output rate; cost must be positive and non-trivial
    assert cost["run_total_usd"] > 0
