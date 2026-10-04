from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from finsentry.mcp.state import dao
from finsentry.mcp.tools.traces import explain_guardrail_decision, get_failing_traces

_TS = datetime.datetime(2026, 10, 4, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _reset_dao() -> None:
    dao._pool = None


def _connect() -> None:
    dao._pool = object()  # truthy sentinel: dao.connected only checks is-not-None


async def test_get_failing_traces_merges_rag_event_and_judge_failures(monkeypatch: Any) -> None:
    _connect()
    rag_rows = [
        {
            "app_trace_id": "t1",
            "status": "blocked",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
            "block_reason": "input_rail_blocked",
            "block_rail": "check prompt injection",
            "error_kind": None,
            "error_detail": None,
        }
    ]
    judge_rows = [
        {
            "app_trace_id": "t1",
            "status": "failed",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
        }
    ]
    calls: list[str] = []

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "FROM rag_events" in sql:
            calls.append("rag_events")
            return rag_rows
        calls.append("judge_verdicts")
        return judge_rows

    monkeypatch.setattr(dao, "fetch_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="any", limit=10)

    assert calls == ["rag_events", "judge_verdicts"]
    assert result.count == 2
    assert result.risingwave_connected is True
    sources = {t.source for t in result.traces}
    assert sources == {"rag_event", "judge_verdict"}


async def test_get_failing_traces_blocked_only_skips_judge_query(monkeypatch: Any) -> None:
    _connect()
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(dao, "fetch_all", fetch_all)

    await get_failing_traces(failure_type="blocked", limit=5)

    assert fetch_all.await_count == 1
    sql = fetch_all.await_args.args[0]
    assert "FROM rag_events" in sql
    assert "LIMIT 5" in sql


async def test_get_failing_traces_offline_returns_empty_not_error(monkeypatch: Any) -> None:
    # dao._pool is None (default) -- fetch_all/fetch_one short-circuit to []/None
    # for real; this test exercises the tool's own handling of that result.
    monkeypatch.setattr(dao, "fetch_all", AsyncMock(return_value=[]))

    result = await get_failing_traces()

    assert result.traces == []
    assert result.count == 0
    assert result.risingwave_connected is False


async def test_explain_guardrail_decision_found_returns_persisted_snapshot(
    monkeypatch: Any,
) -> None:
    _connect()
    row = {
        "app_trace_id": "t1",
        "status": "blocked",
        "endpoint": "/v1/rag/query",
        "timestamp_utc": _TS,
        "input_rail_status": "blocked",
        "block_reason": "input_rail_blocked",
        "block_rail": "check prompt injection",
        "output_rail_trace_snapshot": {},
    }
    monkeypatch.setattr(dao, "fetch_one", AsyncMock(return_value=row))

    result = await explain_guardrail_decision("t1")

    assert result.found is True
    assert result.block_rail == "check prompt injection"
    assert result.timestamp_utc == _TS.isoformat()
    assert "not a NeMo ExplainInfo" in result.note


async def test_explain_guardrail_decision_not_found(monkeypatch: Any) -> None:
    _connect()
    monkeypatch.setattr(dao, "fetch_one", AsyncMock(return_value=None))

    result = await explain_guardrail_decision("nonexistent")

    assert result.found is False
    assert result.risingwave_connected is True
    assert "no matching" in result.note


async def test_explain_guardrail_decision_offline(monkeypatch: Any) -> None:
    monkeypatch.setattr(dao, "fetch_one", AsyncMock(return_value=None))

    result = await explain_guardrail_decision("t1")

    assert result.found is False
    assert result.risingwave_connected is False
    assert "offline" in result.note.lower()
