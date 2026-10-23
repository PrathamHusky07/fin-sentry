"""The trace list leaves out the pytest regression probes that an earlier run published to the
live rag-responses topic. They stay in the store as evidence. Only the UI's list route hides them,
and the MCP tool that shares the query function keeps seeing every row."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import (
    TEST_TRAFFIC_QUERY_PREFIX,
    _dao,
    _fetch_trace_list,
    app,
)
from finsentry.risingwave.dao import risingwave_dsn

_PROBE_SHAPE = re.compile(re.escape(TEST_TRAFFIC_QUERY_PREFIX) + r"[0-9a-f-]{36}")


async def _list_sql(**kwargs: Any) -> tuple[str, tuple[Any, ...]]:
    captured: dict[str, Any] = {}

    async def _capture(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "LEFT JOIN (" in sql:
            captured["sql"], captured["params"] = sql, params
        return []

    with patch("finsentry.dashboard.app._query_all", AsyncMock(side_effect=_capture)):
        await _fetch_trace_list(10, 0, None, None, **kwargs)
    return captured["sql"], captured["params"]


async def test_the_query_function_keeps_every_row_by_default() -> None:
    sql, params = await _list_sql()
    assert "LIKE" not in sql and params == ()


async def test_excluding_test_traffic_adds_one_prefix_and_length_condition() -> None:
    sql, params = await _list_sql(include_test_traffic=False)
    assert "NOT COALESCE(r.query LIKE %s AND LENGTH(r.query) = %s, false)" in sql
    assert params == (f"{TEST_TRAFFIC_QUERY_PREFIX}%", len(TEST_TRAFFIC_QUERY_PREFIX) + 36)


async def test_the_exclusion_composes_with_the_other_filters() -> None:
    sql, params = await _list_sql(include_test_traffic=False, q="apple")
    assert sql.count("%s") == 4  # prefix, length, then the two search patterns
    assert params[2:] == ("%apple%", "%apple%")


async def test_the_list_route_excludes_test_traffic() -> None:
    seen: list[bool] = []

    async def _spy(*_args: Any, include_test_traffic: bool = True, **_kw: Any) -> list[Any]:
        seen.append(include_test_traffic)
        return []

    with patch("finsentry.dashboard.app._fetch_trace_list", AsyncMock(side_effect=_spy)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/traces")).status_code == 200
    assert seen == [False]


async def test_the_exclusion_drops_only_rows_shaped_like_a_probe_against_the_real_store() -> None:
    """Read-only: two SELECTs against RisingWave. Every dropped row has the probe shape, and no
    row of any other shape is dropped, so no genuine request is hidden."""
    try:
        import psycopg

        psycopg.connect(risingwave_dsn(), connect_timeout=3).close()
    except Exception:  # noqa: BLE001 - any connection failure means no store to read
        pytest.skip("RisingWave is not reachable")
    await _dao.open()
    try:
        every = await _fetch_trace_list(500, 0, None, None, include_test_traffic=True)
        kept = await _fetch_trace_list(500, 0, None, None, include_test_traffic=False)
    finally:
        await _dao.close()
    kept_ids = {r["app_trace_id"] for r in kept}
    dropped = [r for r in every if r["app_trace_id"] not in kept_ids]
    assert all(_PROBE_SHAPE.fullmatch(r["query"] or "") for r in dropped)
    assert not any(_PROBE_SHAPE.fullmatch(r["query"] or "") for r in kept)
    assert len(every) == len(kept) + len(dropped)
