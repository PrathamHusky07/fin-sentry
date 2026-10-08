"""A RisingWave failure must read as unavailable, never as an empty result.

GET /traces, /traces/{id} and /metrics/throughput/history answer 503 when RisingWave
is not connected or a query fails against a connected one. A query that ran and matched
nothing is still a 200 with an empty body. These tests drive the real pool object and the
real routes with a fake connection underneath, so the failure travels the real code path.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import _dao, app

Handler = Callable[[str, tuple[Any, ...]], list[dict[str, Any]]]

_TRACE_ROW: dict[str, Any] = {
    "app_trace_id": "trace-1",
    "timestamp_utc": "2026-10-08T19:33:35Z",
    "endpoint": "/v1/rag/query",
    "ticker": "AAPL",
    "query": "q",
    "rag_status": "success",
    "block_reason": None,
    "judge_status": "complete",
}


class _Cursor:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._rows: list[dict[str, Any]] = []

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        await asyncio.sleep(0)  # let concurrent requests interleave
        self._rows = self._handler(sql, params)

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Connection:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def cursor(self, row_factory: object = None) -> _Cursor:
        return _Cursor(self._handler)


class _Pool:
    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    def connection(self) -> _Connection:
        return _Connection(self._handler)


@pytest.fixture
def pool_with() -> Iterator[Callable[[Handler | None], None]]:
    """Install a fake pool under the real DAO. None means RisingWave is not connected."""
    saved = (_dao._pool, _dao._last_query_failed)

    def install(handler: Handler | None) -> None:
        _dao._pool = None if handler is None else _Pool(handler)

    yield install
    _dao._pool, _dao._last_query_failed = saved


def _boom(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    raise RuntimeError("relation rag_events does not exist SECRET-SQL-DETAIL")


def _empty(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return []


async def _get(path: str) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


_ROUTES = ["/traces", "/traces/some-trace-id", "/metrics/throughput/history"]


@pytest.mark.parametrize("path", _ROUTES)
async def test_query_failure_is_a_503_not_an_empty_200(
    path: str, pool_with: Callable[[Handler | None], None]
) -> None:
    pool_with(_boom)
    resp = await _get(path)

    assert resp.status_code == 503
    assert resp.json()["error"] == "risingwave_query_failed"
    assert "SECRET-SQL-DETAIL" not in resp.text  # no exception text reaches the client
    assert "rag_events" not in resp.text  # nor any SQL


@pytest.mark.parametrize("path", _ROUTES)
async def test_unconnected_risingwave_is_a_503_not_an_empty_200(
    path: str, pool_with: Callable[[Handler | None], None]
) -> None:
    pool_with(None)
    resp = await _get(path)

    assert resp.status_code == 503
    assert resp.json()["error"] == "risingwave_unavailable"


async def test_a_genuinely_empty_result_is_still_a_200(
    pool_with: Callable[[Handler | None], None],
) -> None:
    pool_with(_empty)

    traces = await _get("/traces")
    assert traces.status_code == 200
    assert traces.json()["traces"] == []
    assert traces.json()["risingwave_connected"] is True

    detail = await _get("/traces/no-such-trace")
    assert detail.status_code == 200
    assert detail.json()["found"] is False
    assert detail.json()["note"] == "no matching rag_events row"

    history = await _get("/metrics/throughput/history")
    assert history.status_code == 200
    assert history.json()["buckets"] == []
    assert history.json()["risingwave_connected"] is True


async def test_a_failure_in_a_later_query_of_the_same_route_is_still_a_503(
    pool_with: Callable[[Handler | None], None],
) -> None:
    """The trace list runs a second query for the sampled flags. The first succeeds
    with real rows and the second fails. The page must not render rows with every
    trace marked unsampled."""

    def handler(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if "rag_frontier_verdicts" in sql:
            raise RuntimeError("second query fails")
        return [_TRACE_ROW]

    pool_with(handler)
    resp = await _get("/traces")

    assert resp.status_code == 503
    assert resp.json()["error"] == "risingwave_query_failed"


async def test_a_failure_in_a_later_query_of_the_trace_detail_is_still_a_503(
    pool_with: Callable[[Handler | None], None],
) -> None:
    def handler(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if "FROM judge_verdicts" in sql and "FROM rag_events" not in sql:
            raise RuntimeError("judge query fails")
        if "FROM rag_events" in sql:
            return [
                {
                    "app_trace_id": "t",
                    "status": "success",
                    "endpoint": "/v1/rag/query",
                    "ticker": "AAPL",
                    "query": "q",
                    "answer": "a",
                    "confidence": None,
                    "model_used": None,
                    "citations": [],
                    "retrieved_chunk_ids": [],
                    "block_reason": None,
                    "block_rail": None,
                    "error_kind": None,
                    "error_detail": None,
                    "timestamp_utc": "2026-10-08T19:33:35Z",
                }
            ]
        return []

    pool_with(handler)
    resp = await _get("/traces/t")

    assert resp.status_code == 503


async def test_concurrent_requests_cannot_hide_a_failure_behind_anothers_success(
    pool_with: Callable[[Handler | None], None],
) -> None:
    """The pool keeps one last_query_failed flag for all callers. With failing and
    healthy requests interleaved, each response must still follow its own query."""

    def handler(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if params and params[0] == "bad":
            raise RuntimeError("this trace's query fails")
        return []

    pool_with(handler)
    paths = ["/traces/bad" if i % 2 == 0 else f"/traces/ok-{i}" for i in range(40)]
    responses = await asyncio.gather(*(_get(p) for p in paths))

    for path, resp in zip(paths, responses, strict=True):
        expected = 503 if path.endswith("bad") else 200
        assert resp.status_code == expected, path
