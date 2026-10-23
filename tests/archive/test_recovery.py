"""The recovery rehearsal restores the committed archive into disposable databases and reads
it back through the application. It must pass every check, leave nothing behind, and change
nothing it was not meant to touch: the development database and the three live topics. It
needs the Docker Postgres, Redpanda and RisingWave, like the reconcile command it extends."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from aiokafka import AIOKafkaConsumer, TopicPartition  # type: ignore[import-untyped]

from finsentry.archive.export import DEFAULT_DIR, TOPICS
from finsentry.archive.recovery import PREFIX, _checked_name, _database_url, recover
from tests.conftest import TEST_DATABASE_URL

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
DEV_TABLES = ("red_team_runs", "red_team_executions", "investigations", "stream_archive")


@pytest.mark.parametrize("name", ["finsentry", "finsentry_test", "postgres", "finsentry_recovery_"])
def test_only_a_recovery_database_name_can_be_created_or_dropped(name: str) -> None:
    with pytest.raises(ValueError, match="not a recovery database name"):
        _checked_name(name)


def test_a_generated_recovery_name_is_accepted() -> None:
    assert _checked_name(f"{PREFIX}0123abcd") == f"{PREFIX}0123abcd"


async def _end_offsets() -> dict[str, int]:
    consumer: Any = AIOKafkaConsumer(
        bootstrap_servers=BOOTSTRAP, group_id=None, enable_auto_commit=False
    )
    await consumer.start()
    try:
        partitions = [TopicPartition(t, 0) for t in TOPICS]
        ends = await consumer.end_offsets(partitions)
        return {tp.topic: int(off) for tp, off in ends.items()}
    finally:
        await consumer.stop()


def _database_state(url: str) -> tuple[dict[str, int], list[str]]:
    with psycopg.connect(url) as conn:
        counts = {}
        for table in DEV_TABLES:
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
            assert row is not None
            counts[table] = int(row[0])
        leftovers = [
            r[0]
            for r in conn.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE %s", (f"{PREFIX}%",)
            )
        ]
    return counts, leftovers


@pytest.mark.integration
async def test_the_rehearsal_passes_and_leaves_the_live_system_untouched() -> None:
    # The development database sits on the same server as the test database.
    dev_url = _database_url(TEST_DATABASE_URL, "finsentry")
    offsets_before = await _end_offsets()
    dev_before, _ = _database_state(dev_url)

    checks = await recover(DEFAULT_DIR, TEST_DATABASE_URL, BOOTSTRAP)

    failed = [f"{c.name}: {c.detail}" for c in checks if not c.ok]
    assert not failed, failed
    assert len(checks) >= 17
    dev_after, leftovers = _database_state(dev_url)
    assert dev_after == dev_before
    assert leftovers == []
    assert await _end_offsets() == offsets_before
