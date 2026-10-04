from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from finsentry.mcp.state import dao
from finsentry.mcp.tools.injections import search_prompt_injections

_TS = datetime.datetime(2026, 10, 4, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _reset_dao() -> None:
    dao._pool = None


async def test_search_prompt_injections_counts_by_rail(monkeypatch: Any) -> None:
    dao._pool = object()
    rows = [
        {
            "app_trace_id": "t1",
            "endpoint": "/v1/rag/query",
            "block_rail": "check prompt injection",
            "block_reason": "input_rail_blocked",
            "timestamp_utc": _TS,
        },
        {
            "app_trace_id": "t2",
            "endpoint": "/v1/rag/query",
            "block_rail": "check prompt injection",
            "block_reason": "input_rail_blocked",
            "timestamp_utc": _TS,
        },
    ]
    fetch_all = AsyncMock(return_value=rows)
    monkeypatch.setattr(dao, "fetch_all", fetch_all)

    result = await search_prompt_injections(time_window_minutes=60, limit=50)

    assert len(result.direct) == 2
    assert result.direct_count_by_rail == {"check prompt injection": 2}
    assert result.indirect is None
    assert "deferred" in result.indirect_deferred_reason.lower()
    assert result.risingwave_connected is True

    # The real block_rail filter value, not the Python Rail.name.
    sql, params = fetch_all.await_args.args
    assert params[0] == ["check prompt injection"]
    assert "LIMIT 50" in sql


async def test_search_prompt_injections_offline_returns_empty(monkeypatch: Any) -> None:
    monkeypatch.setattr(dao, "fetch_all", AsyncMock(return_value=[]))

    result = await search_prompt_injections()

    assert result.direct == []
    assert result.direct_count_by_rail == {}
    assert result.risingwave_connected is False
