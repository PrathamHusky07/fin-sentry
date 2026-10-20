"""
Shared process state for the MCP server: one RisingWavePool instance,
opened/closed by server.py's lifespan, imported by any tool module that
needs RisingWave access. A single module (rather than defining the pool in
server.py) avoids a circular import between server.py and the tool modules
it registers.
"""

from __future__ import annotations

from typing import Any

from finsentry.risingwave.dao import RisingWavePool, RisingWaveUnavailableError

dao = RisingWavePool()


async def read_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Rows for a read tool. An empty list means the query ran and matched nothing, or that
    RisingWave is offline, which the tool's risingwave_connected flag says. A query that fails
    on a live pool raises RisingWaveQueryError, so a client never reads a failure as no rows."""
    try:
        return await dao.query_all(sql, params)
    except RisingWaveUnavailableError:
        return []


async def read_row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """read_rows for a lookup of one row. None means no row, or an offline pool."""
    try:
        return await dao.query_one(sql, params)
    except RisingWaveUnavailableError:
        return None
