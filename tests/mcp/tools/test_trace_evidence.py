from __future__ import annotations

import datetime
from typing import Any

import pytest

from finsentry.events.trace_api import TraceDetailResponse, TraceListResponse
from finsentry.mcp.state import dao
from finsentry.mcp.tools.trace_evidence import get_trace_detail, search_traces
from finsentry.risingwave.dao import RisingWaveUnavailableError

_TS = datetime.datetime(2026, 10, 7, 9, 30, 0, tzinfo=datetime.UTC)


class _Recorder:
    """Stands in for the RisingWave pool and records every statement it is asked to run."""

    def __init__(self, one: list[dict[str, Any] | None], many: list[list[dict[str, Any]]]) -> None:
        self.statements: list[str] = []
        self._one = one
        self._many = many

    async def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        self.statements.append(sql)
        return self._one.pop(0)

    async def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return self._many.pop(0)


@pytest.fixture(autouse=True)
def _reset_dao() -> None:
    dao._pool = None


def _assert_only_reads(statements: list[str]) -> None:
    assert statements, "the tool ran no query"
    for sql in statements:
        assert sql.lstrip().upper().startswith(("SELECT", "WITH")), sql[:60]
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE "):
            assert verb not in sql.upper(), sql[:60]


async def test_search_traces_returns_the_persisted_investigations_rows(monkeypatch: Any) -> None:
    dao._pool = object()
    recorder = _Recorder(
        one=[],
        many=[
            [
                {
                    "app_trace_id": "t1",
                    "timestamp_utc": _TS,
                    "endpoint": "/v1/rag/query",
                    "ticker": "AAPL",
                    "query": "What were the risk factors?",
                    "rag_status": "blocked",
                    "block_reason": "input_rail_blocked",
                    "judge_status": None,
                }
            ],
            [],  # frontier-sampled lookup for the page
        ],
    )
    monkeypatch.setattr(dao, "query_all", recorder.query_all)

    result = await search_traces(limit=1, ticker="AAPL", rag_status="blocked")

    assert isinstance(result, TraceListResponse)
    assert [t.app_trace_id for t in result.traces] == ["t1"]
    assert result.traces[0].judge_state == "blocked_before_evaluation"
    assert result.traces[0].frontier_sampled is False
    assert result.next_offset == 1  # a full page, so there may be more
    assert result.risingwave_connected is True
    _assert_only_reads(recorder.statements)


async def test_search_traces_has_no_next_offset_on_a_short_page(monkeypatch: Any) -> None:
    dao._pool = object()
    recorder = _Recorder(one=[], many=[[]])
    monkeypatch.setattr(dao, "query_all", recorder.query_all)

    result = await search_traces(limit=20)

    assert result.traces == [] and result.next_offset is None


@pytest.mark.parametrize("limit", [0, -1, 101, 500])
async def test_search_traces_bounds_the_page_size(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be"):
        await search_traces(limit=limit)


async def test_search_traces_rejects_a_negative_offset() -> None:
    with pytest.raises(ValueError, match="offset must be >= 0"):
        await search_traces(offset=-1)


async def test_an_unavailable_risingwave_raises_instead_of_reading_as_no_traces() -> None:
    with pytest.raises(RisingWaveUnavailableError):
        await search_traces()
    with pytest.raises(RisingWaveUnavailableError):
        await get_trace_detail("t1")


async def test_get_trace_detail_returns_the_persisted_trace_with_judge_state(
    monkeypatch: Any,
) -> None:
    dao._pool = object()
    rag_row = {
        "app_trace_id": "t1",
        "status": "success",
        "endpoint": "/v1/rag/query",
        "ticker": "AAPL",
        "query": "q",
        "answer": "a",
        "confidence": "high",
        "model_used": "llama3.1:8b",
        "citations": [{"chunk_id": "c1", "quote": "x"}],
        "retrieved_chunk_ids": ["c1"],
        "block_reason": None,
        "block_rail": None,
        "error_kind": None,
        "error_detail": None,
        "timestamp_utc": _TS,
    }
    judge_row = {
        "status": "complete",
        "timestamp_utc": _TS,
        "faithfulness_score": 0.9,
        "faithfulness_status": "complete",
        "answer_relevance_score": 0.8,
        "answer_relevance_status": "complete",
        "context_relevance_score": 0.7,
        "context_relevance_status": "complete",
    }
    recorder = _Recorder(one=[rag_row, judge_row, None], many=[])
    monkeypatch.setattr(dao, "query_one", recorder.query_one)

    result = await get_trace_detail("t1")

    assert isinstance(result, TraceDetailResponse)
    assert result.found is True and result.rag_status == "success"
    assert result.judge_state == "evaluated"
    assert result.flash is not None and result.flash.faithfulness_score == 0.9
    assert result.frontier.sampled is False
    assert result.retrieved_chunk_ids == ["c1"]
    _assert_only_reads(recorder.statements)


async def test_get_trace_detail_reports_found_false_for_an_unknown_trace(monkeypatch: Any) -> None:
    dao._pool = object()
    recorder = _Recorder(one=[None], many=[])
    monkeypatch.setattr(dao, "query_one", recorder.query_one)

    result = await get_trace_detail("missing")

    assert result.found is False and result.answer is None
    assert result.note == "no matching rag_events row"
    _assert_only_reads(recorder.statements)
