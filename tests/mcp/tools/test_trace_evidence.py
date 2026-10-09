from __future__ import annotations

import datetime
from typing import Any

import pytest

from finsentry.events.trace_api import TraceDetailResponse, TraceListResponse
from finsentry.mcp.state import dao
from finsentry.mcp.tools.trace_evidence import MAX_QUERY_CHARS, get_trace_detail, search_traces
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


async def test_search_traces_cuts_a_long_stored_query_like_get_trace_detail(
    monkeypatch: Any,
) -> None:
    dao._pool = object()
    long_query = "x" * (MAX_QUERY_CHARS + 200)
    row = {
        "app_trace_id": "t1",
        "timestamp_utc": _TS,
        "endpoint": "/v1/rag/query",
        "ticker": "AAPL",
        "query": long_query,
        "rag_status": "success",
        "block_reason": None,
        "judge_status": None,
    }
    recorder = _Recorder(one=[], many=[[row], []])
    monkeypatch.setattr(dao, "query_all", recorder.query_all)
    listed = await search_traces(limit=1)

    rag_row, judge_row = _detail_rows(query=long_query)
    detail_recorder = _Recorder(one=[rag_row, judge_row, None], many=[])
    monkeypatch.setattr(dao, "query_one", detail_recorder.query_one)
    detail = await get_trace_detail("t1")

    assert len(listed.traces[0].query) == MAX_QUERY_CHARS + 3
    assert listed.traces[0].query == detail.query


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


@pytest.mark.parametrize("value", [True, False, None])
async def test_search_traces_passes_the_disagreement_filter_through_unchanged(
    monkeypatch: Any, value: bool | None
) -> None:
    seen: list[Any] = []

    async def spy(*args: Any) -> list[dict[str, Any]]:
        seen.append(args[7])
        return []

    dao._pool = object()
    monkeypatch.setattr("finsentry.mcp.tools.trace_evidence._fetch_trace_list", spy)

    await search_traces(disagreement=value)

    assert seen == [value]


_SECRET = "postgresql://svc:hunter2@db.internal:5432/finsentry"


def _detail_rows(**over: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    rag_row = {
        "app_trace_id": "t1",
        "status": "error",
        "endpoint": "/v1/rag/query",
        "ticker": "AAPL",
        "query": "q",
        "answer": "The model said something unredacted, call 555-12-3456.",
        "confidence": "high",
        "model_used": "llama3.1:8b",
        "citations": [{"chunk_id": "c1", "quote": "a model-written quote"}],
        "retrieved_chunk_ids": ["c1"],
        "block_reason": None,
        "block_rail": None,
        "error_kind": "OperationalError",
        "error_detail": f"could not connect to {_SECRET}",
        "timestamp_utc": _TS,
        **over,
    }
    return rag_row, None


async def test_get_trace_detail_never_surfaces_error_detail_answer_or_citation_quotes(
    monkeypatch: Any,
) -> None:
    dao._pool = object()
    rag_row, judge_row = _detail_rows()
    recorder = _Recorder(one=[rag_row, judge_row, None], many=[])
    monkeypatch.setattr(dao, "query_one", recorder.query_one)

    result = await get_trace_detail("t1")

    assert result.error_detail is None and result.answer is None
    assert result.error_kind == "OperationalError"
    assert result.citations == [{"chunk_id": "c1"}]
    assert result.retrieved_chunk_ids == ["c1"]
    dumped = result.model_dump_json()
    for leaked in ("hunter2", "db.internal", "555-12-3456", "a model-written quote"):
        assert leaked not in dumped
    assert "withheld by this tool" in result.note


async def test_get_trace_detail_cuts_a_long_stored_query(monkeypatch: Any) -> None:
    dao._pool = object()
    rag_row, judge_row = _detail_rows(query="x" * (MAX_QUERY_CHARS + 200))
    recorder = _Recorder(one=[rag_row, judge_row, None], many=[])
    monkeypatch.setattr(dao, "query_one", recorder.query_one)

    result = await get_trace_detail("t1")

    assert result.query is not None and len(result.query) == MAX_QUERY_CHARS + 3


async def test_get_trace_detail_withholds_the_frontier_rubric_reasoning(monkeypatch: Any) -> None:
    dao._pool = object()
    rag_row, _ = _detail_rows(status="success", error_kind=None, error_detail=None)
    frontier_row = {
        "per_judge_results": [
            {
                "judge_id": "gemini-rubric",
                "faithfulness_score": 0.2,
                "evidence": {
                    "rubric_reasoning": "The answer claims 555-12-3456 which is unsupported.",
                    "cited_chunks_supporting": ["c1"],
                    "cited_chunks_contradicting": [],
                },
            }
        ],
        "verdict": "unfaithful",
        "evaluation_ts": _TS,
    }
    recorder = _Recorder(one=[rag_row, None, frontier_row], many=[])
    monkeypatch.setattr(dao, "query_one", recorder.query_one)

    result = await get_trace_detail("t1")

    evidence = result.frontier.evidence
    assert evidence is not None and evidence.rubric_reasoning is None
    assert evidence.faithfulness_score == 0.2 and evidence.cited_chunks_supporting == ["c1"]
    assert "555-12-3456" not in result.model_dump_json()
