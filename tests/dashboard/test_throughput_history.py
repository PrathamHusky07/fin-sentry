"""GET /metrics/throughput/history: the latest persisted one-minute buckets of
mv_request_throughput_1m, oldest first, never filled in or interpolated."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import app

_UTC = datetime.UTC


def _row(minute: int, total: int = 1, errors: int = 0) -> dict[str, Any]:
    start = datetime.datetime(2026, 10, 6, 2, minute, tzinfo=_UTC)
    return {
        "window_start": start,
        "window_end": start + datetime.timedelta(minutes=1),
        "total_requests": total,
        "success_count": total - errors,
        "blocked_count": 0,
        "error_count": errors,
        "avg_latency_ms": Decimal("100.0"),
        "p95_latency_ms": Decimal("100.5"),
    }


async def _get(rows: list[dict[str, Any]], **params: Any) -> Any:
    fetch = AsyncMock(return_value=rows)
    with patch("finsentry.dashboard.app._query_all", fetch):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/throughput/history", params=params)
    return resp, fetch


async def test_returns_persisted_buckets_oldest_first_with_an_explicit_window() -> None:
    # The query returns newest first; the response is oldest first.
    resp, _ = await _get([_row(26, total=3), _row(25), _row(10, total=5, errors=2)])

    assert resp.status_code == 200
    body = resp.json()
    starts = [b["window_start"] for b in body["buckets"]]
    assert starts == sorted(starts)
    assert [b["total_requests"] for b in body["buckets"]] == [5, 1, 3]
    assert body["buckets"][0]["error_count"] == 2
    assert body["window_start"] == body["buckets"][0]["window_start"]
    assert body["window_end"] == body["buckets"][-1]["window_end"]
    assert body["limit"] == 60
    assert body["generated_at"]
    assert body["buckets"][0]["avg_latency_ms"] == 100.0


async def test_does_not_fill_the_minutes_between_buckets() -> None:
    resp, _ = await _get([_row(26), _row(10)])

    assert len(resp.json()["buckets"]) == 2


async def test_an_empty_view_is_an_empty_list_not_a_made_up_window() -> None:
    resp, _ = await _get([])

    body = resp.json()
    assert body["buckets"] == []
    assert body["window_start"] is None
    assert body["window_end"] is None


async def test_the_query_reads_only_the_view_and_inlines_the_limit() -> None:
    _, fetch = await _get([], limit=25)

    sql = fetch.call_args.args[0]
    assert "FROM mv_request_throughput_1m" in sql
    assert "LEFT JOIN mv_request_latency_exact_1m" in sql
    assert "ORDER BY l.window_start DESC" in sql
    assert "LIMIT 25" in sql
    for write in ("INSERT", "UPDATE", "DELETE", "DROP"):
        assert write not in sql.upper()


async def test_limit_is_range_checked() -> None:
    for bad in (0, -1, 501):
        resp, fetch = await _get([], limit=bad)
        assert resp.status_code == 422
        fetch.assert_not_called()
