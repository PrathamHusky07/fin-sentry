"""
Shared RisingWave access primitives: DSN, connection pool lifecycle, and
offline-safe fetch_one/fetch_all.

Extracted from finsentry/dashboard/app.py (Day 7) so the dashboard and the
MCP server consume one connection/fetch layer instead of two divergent
copies. Domain queries (which views, which filters) stay with each
consumer -- this module only owns the DSN, the pool, and offline semantics:
a query against a closed/failed pool returns None/[] rather than raising,
so a caller never crashes just because RisingWave isn't running.

Environment variables (unchanged from the dashboard's prior convention):
    RISINGWAVE_HOST   (default: localhost)
    RISINGWAVE_PORT   (default: 4566)
    RISINGWAVE_USER    (default: root)
    RISINGWAVE_DB     (default: dev)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import psycopg
import psycopg.rows

log = logging.getLogger(__name__)


def risingwave_dsn() -> str:
    host = os.getenv("RISINGWAVE_HOST", "localhost")
    port = os.getenv("RISINGWAVE_PORT", "4566")
    user = os.getenv("RISINGWAVE_USER", "root")
    db = os.getenv("RISINGWAVE_DB", "dev")
    return f"postgresql://{user}@{host}:{port}/{db}"


class RisingWavePool:
    """Owns one async connection pool. A pool that failed to open (or was
    never opened) puts this object in offline mode: fetch_one/fetch_all
    return None/[] instead of raising, matching the dashboard's established
    "static demo" degradation instead of a crash.

    `connected` and `last_query_failed` together distinguish three states a
    caller may need to tell apart: connection unavailable (`connected` is
    False), the most recent query against an established pool succeeded
    (`connected` is True, `last_query_failed` is False), and a query failed
    against an established pool -- a SQL error, not a dropped connection
    (`connected` is True, `last_query_failed` is True). fetch_one/fetch_all's
    None/[] return contract is unchanged by this -- `last_query_failed` is
    additive state for callers that need to tell "no rows" apart from "the
    query errored," not a replacement for it."""

    def __init__(self) -> None:
        self._pool: Any = None
        self._last_query_failed: bool = False

    @property
    def connected(self) -> bool:
        return self._pool is not None

    @property
    def last_query_failed(self) -> bool:
        """Whether the most recently completed fetch_one/fetch_all raised
        against an established pool. Meaningless while `connected` is False
        (there is no pool to query against)."""
        return self._last_query_failed

    async def open(self) -> None:
        try:
            import psycopg_pool  # lazy; optional at import time

            pool = psycopg_pool.AsyncConnectionPool(
                risingwave_dsn(), min_size=1, max_size=3, open=False
            )
            await pool.open(wait=True)
            self._pool = pool
        except Exception as exc:
            log.warning("RisingWave connection failed -- running in offline mode: %s", exc)
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        if self._pool is None:
            return None
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(sql, params)
                    row: dict[str, Any] | None = await cur.fetchone()
                    self._last_query_failed = False
                    return row
        except Exception:
            log.exception("RisingWave query failed: %s", sql[:80])
            self._last_query_failed = True
            return None

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if self._pool is None:
            return []
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(sql, params)
                    rows: list[dict[str, Any]] = await cur.fetchall()
                    self._last_query_failed = False
                    return rows
        except Exception:
            log.exception("RisingWave query failed: %s", sql[:80])
            self._last_query_failed = True
            return []
