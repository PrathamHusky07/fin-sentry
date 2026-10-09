from __future__ import annotations

from typing import Any

import pytest

from finsentry.risingwave.dao import (
    RisingWavePool,
    RisingWaveQueryError,
    RisingWaveUnavailableError,
    risingwave_dsn,
)


class _FakeCursor:
    def __init__(self, row: dict[str, Any] | None, rows: list[dict[str, Any]], fail: bool) -> None:
        self._row = row
        self._rows = rows
        self._fail = fail

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        if self._fail:
            raise RuntimeError("simulated SQL error")

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def cursor(self, row_factory: object = None) -> _FakeCursor:
        return self._cursor


class _FakePool:
    """Stands in for `self._pool` on an already-open RisingWavePool: an
    established connection whose query either succeeds or raises, so tests
    can exercise fetch_one/fetch_all's query-failure path without a real
    database."""

    def __init__(
        self,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        fail: bool = False,
    ) -> None:
        self._cursor = _FakeCursor(row, rows or [], fail)

    def connection(self) -> _FakeConnection:
        return _FakeConnection(self._cursor)


def test_risingwave_dsn_uses_defaults(monkeypatch: object) -> None:
    import os

    for key in ("RISINGWAVE_HOST", "RISINGWAVE_PORT", "RISINGWAVE_USER", "RISINGWAVE_DB"):
        os.environ.pop(key, None)
    assert risingwave_dsn() == "postgresql://root@localhost:4566/dev"


async def test_unopened_pool_is_offline_and_fetches_return_empty() -> None:
    pool = RisingWavePool()
    assert not pool.connected
    assert await pool.fetch_one("SELECT 1") is None
    assert await pool.fetch_all("SELECT 1") == []


async def test_successful_query_against_established_pool_is_not_flagged_failed() -> None:
    pool = RisingWavePool()
    pool._pool = _FakePool(row={"x": 1}, rows=[{"x": 1}])

    assert await pool.fetch_one("SELECT 1") == {"x": 1}
    assert pool.connected
    assert pool.last_query_failed is False

    assert await pool.fetch_all("SELECT 1") == [{"x": 1}]
    assert pool.connected
    assert pool.last_query_failed is False


async def test_query_failure_against_established_pool_is_not_reported_as_offline() -> None:
    """A SQL error on a healthy pool must read as a query failure, not a
    dropped connection: connected stays True, last_query_failed flips True."""
    pool = RisingWavePool()
    pool._pool = _FakePool(fail=True)

    assert await pool.fetch_one("SELECT 1") is None
    assert pool.connected is True
    assert pool.last_query_failed is True

    pool._pool = _FakePool(fail=True)
    assert await pool.fetch_all("SELECT 1") == []
    assert pool.connected is True
    assert pool.last_query_failed is True


async def test_close_on_never_opened_pool_is_a_no_op() -> None:
    pool = RisingWavePool()
    await pool.close()  # must not raise
    assert not pool.connected


async def test_close_after_open_clears_connected_state() -> None:
    pool = RisingWavePool()

    class _ClosablePool(_FakePool):
        def __init__(self) -> None:
            super().__init__(row={"x": 1})
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake = _ClosablePool()
    pool._pool = fake

    await pool.close()

    assert fake.closed is True
    assert not pool.connected


async def test_query_methods_raise_on_an_unopened_pool() -> None:
    pool = RisingWavePool()
    with pytest.raises(RisingWaveUnavailableError):
        await pool.query_one("SELECT 1")
    with pytest.raises(RisingWaveUnavailableError):
        await pool.query_all("SELECT 1")


async def test_query_methods_raise_on_a_failed_query_without_leaking_its_text() -> None:
    pool = RisingWavePool()
    pool._pool = _FakePool(fail=True)
    with pytest.raises(RisingWaveQueryError) as one:
        await pool.query_one("SELECT 1")
    with pytest.raises(RisingWaveQueryError) as many:
        await pool.query_all("SELECT 1")
    assert "simulated SQL error" not in str(one.value) + str(many.value)


async def test_query_methods_return_empty_for_a_query_that_matched_nothing() -> None:
    pool = RisingWavePool()
    pool._pool = _FakePool(row=None, rows=[])
    assert await pool.query_one("SELECT 1") is None
    assert await pool.query_all("SELECT 1") == []


async def test_failed_query_count_moves_only_on_a_failure_and_a_later_success_keeps_it() -> None:
    """last_query_failed is overwritten by the next call, so a tool that runs two queries
    can lose a failure. The count only goes up."""
    pool = RisingWavePool()
    assert pool.failed_query_count == 0
    pool._pool = _FakePool(rows=[{"x": 1}])
    await pool.fetch_all("SELECT 1")
    assert pool.failed_query_count == 0

    pool._pool = _FakePool(fail=True)
    await pool.fetch_all("SELECT 1")
    await pool.fetch_one("SELECT 1")
    assert pool.failed_query_count == 2

    pool._pool = _FakePool(rows=[{"x": 1}])
    await pool.fetch_all("SELECT 1")
    assert pool.last_query_failed is False
    assert pool.failed_query_count == 2


async def test_an_offline_pool_does_not_count_as_a_failed_query() -> None:
    pool = RisingWavePool()
    await pool.fetch_all("SELECT 1")
    assert pool.failed_query_count == 0
