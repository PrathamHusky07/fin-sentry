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
            "app_trace_id": "t2",
            "status": "failed",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
            "total_gemini_calls": 2,
        }
    ]
    calls: list[str] = []

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "FROM rag_events" in sql:
            calls.append("rag_events")
            return rag_rows
        calls.append("judge_verdicts")
        return judge_rows

    monkeypatch.setattr(dao, "query_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="any", limit=10)

    assert calls == ["rag_events", "judge_verdicts"]
    assert result.classification_counts == {
        "guardrail_blocked": 1,
        "judge_pipeline_failure": 1,
    }
    assert result.unique_trace_count == 2
    assert result.score_filter_match_count == 0
    assert result.risingwave_connected is True
    sources = {t.source for t in result.traces}
    assert sources == {"rag_event", "judge_verdict"}


async def test_get_failing_traces_classifies_real_d7_blocked_request_as_judge_skipped(
    monkeypatch: Any,
) -> None:
    """Regression test on the real Day 7 blocked-request pattern
    (app_trace_id=7b7a37e6-b22b-45da-a8df-d0a98a095236, see build-log): a
    guardrail-blocked request produces a judge_verdicts row with
    status='failed' and total_gemini_calls=0 because there is nothing to
    judge on a blocked request with no answer. That is a judge-skip, not a
    pipeline failure -- classification_counts must show both counted
    separately, not lumped together as "2 failures"."""
    _connect()
    trace_id = "7b7a37e6-b22b-45da-a8df-d0a98a095236"
    rag_rows = [
        {
            "app_trace_id": trace_id,
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
            "app_trace_id": trace_id,
            "status": "failed",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
            "total_gemini_calls": 0,
        }
    ]

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return rag_rows if "FROM rag_events" in sql else judge_rows

    monkeypatch.setattr(dao, "query_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="any", limit=10)

    judge_trace = next(t for t in result.traces if t.source == "judge_verdict")
    assert judge_trace.classification == "judge_skipped"
    assert judge_trace.total_gemini_calls == 0

    rag_trace = next(t for t in result.traces if t.source == "rag_event")
    assert rag_trace.classification == "guardrail_blocked"

    assert result.classification_counts == {"guardrail_blocked": 1, "judge_skipped": 1}
    assert result.unique_trace_count == 1


async def test_get_failing_traces_classifies_gemini_calls_gt_zero_as_pipeline_failure(
    monkeypatch: Any,
) -> None:
    _connect()
    judge_rows = [
        {
            "app_trace_id": "t3",
            "status": "partial",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
            "total_gemini_calls": 2,
        }
    ]

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [] if "FROM rag_events" in sql else judge_rows

    monkeypatch.setattr(dao, "query_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="judge_failed", limit=10)

    assert len(result.traces) == 1
    assert result.traces[0].classification == "judge_pipeline_failure"
    assert result.classification_counts == {"judge_pipeline_failure": 1}


async def test_get_failing_traces_score_below_flags_match_not_failure(monkeypatch: Any) -> None:
    _connect()
    complete_rows = [
        {
            "app_trace_id": "t4",
            "status": "complete",
            "endpoint": "/v1/rag/query",
            "ticker": "AAPL",
            "timestamp_utc": _TS,
            "answer_relevance_score": 0.4,
            "context_relevance_score": 0.9,
        }
    ]

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "FROM rag_events" in sql:
            return []
        if "j.status = 'complete'" in sql:
            return complete_rows
        return []

    monkeypatch.setattr(dao, "query_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="any", limit=10, score_below=0.7)

    assert len(result.traces) == 1
    matched = result.traces[0]
    assert matched.classification is None
    assert matched.status == "complete"
    assert len(matched.matched_score_filter) == 1
    assert matched.matched_score_filter[0].dimension == "answer_relevance"
    assert matched.matched_score_filter[0].score == 0.4
    assert matched.matched_score_filter[0].threshold == 0.7
    assert result.classification_counts == {}
    assert result.score_filter_match_count == 1
    assert result.unique_trace_count == 1


async def test_get_failing_traces_score_below_none_leaves_behavior_unchanged(
    monkeypatch: Any,
) -> None:
    _connect()
    calls: list[str] = []

    async def fake_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        calls.append(sql)
        return []

    monkeypatch.setattr(dao, "query_all", fake_fetch_all)

    result = await get_failing_traces(failure_type="any", limit=10, score_below=None)

    assert not any("j.status = 'complete'" in sql for sql in calls)
    assert result.traces == []
    assert result.classification_counts == {}
    assert result.score_filter_match_count == 0
    assert result.unique_trace_count == 0


async def test_get_failing_traces_blocked_only_skips_judge_query(monkeypatch: Any) -> None:
    _connect()
    fetch_all = AsyncMock(return_value=[])
    monkeypatch.setattr(dao, "query_all", fetch_all)

    await get_failing_traces(failure_type="blocked", limit=5)

    assert fetch_all.await_count == 1
    sql = fetch_all.await_args.args[0]
    assert "FROM rag_events" in sql
    assert "LIMIT 5" in sql


async def test_get_failing_traces_offline_returns_empty_not_error(monkeypatch: Any) -> None:
    # dao._pool is None (default) -- fetch_all/fetch_one short-circuit to []/None
    # for real; this test exercises the tool's own handling of that result.
    monkeypatch.setattr(dao, "query_all", AsyncMock(return_value=[]))

    result = await get_failing_traces()

    assert result.traces == []
    assert result.classification_counts == {}
    assert result.unique_trace_count == 0
    assert result.risingwave_connected is False


async def test_get_failing_traces_rejects_out_of_bounds_limit() -> None:
    with pytest.raises(ValueError, match="limit must be"):
        await get_failing_traces(limit=0)
    with pytest.raises(ValueError, match="limit must be"):
        await get_failing_traces(limit=501)


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
    monkeypatch.setattr(dao, "query_one", AsyncMock(return_value=row))

    result = await explain_guardrail_decision("t1")

    assert result.found is True
    assert result.block_rail == "check prompt injection"
    assert result.timestamp_utc == _TS.isoformat()
    assert "not a NeMo ExplainInfo" in result.note


async def test_explain_guardrail_decision_not_found(monkeypatch: Any) -> None:
    _connect()
    monkeypatch.setattr(dao, "query_one", AsyncMock(return_value=None))

    result = await explain_guardrail_decision("nonexistent")

    assert result.found is False
    assert result.risingwave_connected is True
    assert "no matching" in result.note


async def test_explain_guardrail_decision_offline(monkeypatch: Any) -> None:
    monkeypatch.setattr(dao, "query_one", AsyncMock(return_value=None))

    result = await explain_guardrail_decision("t1")

    assert result.found is False
    assert result.risingwave_connected is False
    assert "offline" in result.note.lower()
