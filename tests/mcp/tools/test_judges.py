from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from finsentry.mcp.state import dao
from finsentry.mcp.tools.judges import get_judge_scores

_TS = datetime.datetime(2026, 10, 4, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _reset_dao() -> None:
    dao._pool = None


async def test_get_judge_scores_maps_flash_and_frontier_rows(monkeypatch: Any) -> None:
    dao._pool = object()
    rows = [
        {
            "judge_tier": "flash",
            "judge_model": "gemini-3.6-flash",
            "status": "complete",
            "timestamp_utc": _TS,
            "faithfulness_score": 0.9,
            "faithfulness_status": "complete",
            "answer_relevance_score": 0.8,
            "answer_relevance_status": "complete",
            "context_relevance_score": 0.85,
            "context_relevance_status": "complete",
            "total_input_tokens": 100,
            "total_output_tokens": 20,
            "total_thoughts_tokens": 0,
            "total_gemini_calls": 3,
            "total_cost_usd": 0.001,
            "evaluation_latency_ms": 500,
        },
        {
            "judge_tier": "frontier",
            "judge_model": "gemini-3.6-flash",
            "status": "complete",
            "timestamp_utc": _TS,
            "faithfulness_score": 0.95,
            "faithfulness_status": "complete",
            "answer_relevance_score": None,
            "answer_relevance_status": None,
            "context_relevance_score": None,
            "context_relevance_status": None,
            "total_input_tokens": 200,
            "total_output_tokens": 40,
            "total_thoughts_tokens": 10,
            "total_gemini_calls": 1,
            "total_cost_usd": 0.002,
            "evaluation_latency_ms": 800,
        },
    ]
    monkeypatch.setattr(dao, "query_all", AsyncMock(return_value=rows))

    result = await get_judge_scores("t1")

    assert result.count == 2
    tiers = {v.judge_tier for v in result.verdicts}
    assert tiers == {"flash", "frontier"}
    assert result.risingwave_connected is True
    frontier = next(v for v in result.verdicts if v.judge_tier == "frontier")
    assert frontier.faithfulness_score == 0.95
    assert frontier.answer_relevance_score is None


async def test_get_judge_scores_offline_returns_empty(monkeypatch: Any) -> None:
    monkeypatch.setattr(dao, "query_all", AsyncMock(return_value=[]))

    result = await get_judge_scores("t1")

    assert result.verdicts == []
    assert result.count == 0
    assert result.risingwave_connected is False
