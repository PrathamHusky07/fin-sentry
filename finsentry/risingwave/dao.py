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


class RisingWaveUnavailableError(Exception):
    """There is no connection pool, so no query could be attempted."""


class RisingWaveQueryError(Exception):
    """A query raised against an established pool: a SQL error or a dropped
    connection, not an empty result."""


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
    query errored," not a replacement for it. It is one flag shared by every
    caller, so concurrent requests can overwrite each other's reading. A caller
    that must not mistake a failure for an empty result uses query_one/query_all,
    which raise on the failing call itself."""

    def __init__(self) -> None:
        self._pool: Any = None
        self._last_query_failed: bool = False
        self._failed_query_count: int = 0

    @property
    def connected(self) -> bool:
        return self._pool is not None

    @property
    def last_query_failed(self) -> bool:
        """Whether the most recently completed fetch_one/fetch_all raised
        against an established pool. Meaningless while `connected` is False
        (there is no pool to query against)."""
        return self._last_query_failed

    @property
    def failed_query_count(self) -> int:
        """How many fetch_one/fetch_all calls have raised against an established pool since
        this object was made. Unlike last_query_failed it is never overwritten by a later
        success, so a caller that compares it before and after a tool call sees a failure even
        when the tool ran a second query that succeeded."""
        return self._failed_query_count

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

    async def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Like fetch_one, but a failure raises instead of reading as no row.
        None means the query ran and matched nothing."""
        if self._pool is None:
            raise RisingWaveUnavailableError("RisingWave is not connected")
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(sql, params)
                    row: dict[str, Any] | None = await cur.fetchone()
                    return row
        except Exception as exc:
            log.exception("RisingWave query failed: %s", sql[:80])
            raise RisingWaveQueryError("RisingWave query failed") from exc

    async def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Like fetch_all, but a failure raises instead of reading as no rows.
        An empty list means the query ran and matched nothing."""
        if self._pool is None:
            raise RisingWaveUnavailableError("RisingWave is not connected")
        try:
            async with self._pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(sql, params)
                    rows: list[dict[str, Any]] = await cur.fetchall()
                    return rows
        except Exception as exc:
            log.exception("RisingWave query failed: %s", sql[:80])
            raise RisingWaveQueryError("RisingWave query failed") from exc

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        try:
            row = await self.query_one(sql, params)
        except RisingWaveUnavailableError:
            return None
        except RisingWaveQueryError:
            self._last_query_failed = True
            self._failed_query_count += 1
            return None
        self._last_query_failed = False
        return row

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            rows = await self.query_all(sql, params)
        except RisingWaveUnavailableError:
            return []
        except RisingWaveQueryError:
            self._last_query_failed = True
            self._failed_query_count += 1
            return []
        self._last_query_failed = False
        return rows
