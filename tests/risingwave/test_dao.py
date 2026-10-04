from __future__ import annotations

from finsentry.risingwave.dao import RisingWavePool, risingwave_dsn


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


async def test_close_on_never_opened_pool_is_a_no_op() -> None:
    pool = RisingWavePool()
    await pool.close()  # must not raise
    assert not pool.connected
