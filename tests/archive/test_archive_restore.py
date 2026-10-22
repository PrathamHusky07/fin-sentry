"""Restoring the committed archive: counts, ids and checksums reconcile with the manifest,
a second restore adds nothing, and a row that already exists is never overwritten. Runs on
the test database and never touches a topic, RisingWave or a model."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest

from finsentry.archive.export import DEFAULT_DIR, TABLE_ORDER, TOPICS
from finsentry.archive.format import MANIFEST, dataset_ids, ids_digest, read_lines
from finsentry.archive.restore import ArchiveInvalidError, materialize, republish
from tests.conftest import TEST_DATABASE_URL

_TABLES = (
    "investigation_events",
    "investigations",
    "red_team_executions",
    "red_team_runs",
    "stream_archive",
)


def _wipe() -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        for table in _TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    _wipe()
    yield
    _wipe()


def _count(table: str) -> int:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    return int(row[0])


def test_a_restore_reproduces_every_archived_count_and_id() -> None:
    manifest = json.loads((DEFAULT_DIR / MANIFEST).read_text())
    inserted = materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    for name, entry in manifest["datasets"].items():
        assert inserted[name] == entry["records"], name
    for table in TABLE_ORDER:
        assert _count(table) == manifest["datasets"][table]["records"]
    assert _count("stream_archive") == sum(manifest["datasets"][t]["records"] for t in TOPICS)

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        for topic in TOPICS:
            stored = [
                r[0]
                for r in conn.execute(
                    "SELECT record_sha256 FROM stream_archive WHERE topic = %s", (topic,)
                ).fetchall()
            ]
            archived = dataset_ids(
                topic, "stream", read_lines(DEFAULT_DIR / "stream" / f"{topic}.jsonl")
            )
            assert (
                ids_digest(stored)
                == ids_digest(archived)
                == manifest["datasets"][topic]["ids_sha256"]
            )


def test_restored_table_rows_are_byte_identical_to_the_archived_rows() -> None:
    materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        for table in TABLE_ORDER:
            order = TABLE_ORDER[table]
            live = {
                str(r[0])
                for r in conn.execute(
                    f"SELECT to_jsonb(t)::text FROM {table} t ORDER BY {order}"
                ).fetchall()  # noqa: S608
            }
            archived = set(
                (DEFAULT_DIR / "postgres" / f"{table}.jsonl").read_text("utf-8").splitlines()
            )
            assert live == archived, table


def test_a_second_restore_adds_nothing() -> None:
    first = materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    before = {t: _count(t) for t in (*TABLE_ORDER, "stream_archive")}
    second = materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    assert sum(first.values()) > 0
    assert set(second.values()) == {0}
    assert {t: _count(t) for t in before} == before


def test_a_restore_never_overwrites_a_row_that_already_exists() -> None:
    materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        run = conn.execute("SELECT run_id FROM red_team_runs LIMIT 1").fetchone()
        assert run is not None
        conn.execute(
            "UPDATE red_team_runs SET failure_reason = 'edited after restore' WHERE run_id = %s",
            (run[0],),
        )
    materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        kept = conn.execute(
            "SELECT failure_reason FROM red_team_runs WHERE run_id = %s", (run[0],)
        ).fetchone()
    assert kept == ("edited after restore",)


def test_a_restore_fills_in_only_what_is_missing() -> None:
    materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM investigation_events WHERE (investigation_id, seq) IN"
            " (SELECT investigation_id, seq FROM investigation_events LIMIT 3)"
        )
        conn.execute(
            "DELETE FROM stream_archive WHERE topic = 'judge-verdicts' AND source_offset % 50 = 0"
        )
    removed_events = json.loads((DEFAULT_DIR / MANIFEST).read_text())["datasets"][
        "investigation_events"
    ]["records"] - _count("investigation_events")
    again = materialize(DEFAULT_DIR, TEST_DATABASE_URL)
    assert again["investigation_events"] == removed_events == 3
    assert again["judge-verdicts"] > 0
    assert again["rag-responses"] == 0 and again["red_team_runs"] == 0


def test_a_restore_refuses_an_archive_that_does_not_verify(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / MANIFEST).write_text('{"schema_version": 7, "datasets": {}}')
    with pytest.raises(ArchiveInvalidError):
        materialize(broken, TEST_DATABASE_URL)
    assert _count("stream_archive") == 0


async def test_a_live_topic_is_refused_without_the_flag_and_while_a_consumer_runs() -> None:
    with pytest.raises(PermissionError, match="live topic"):
        await republish(DEFAULT_DIR, "rag-responses", "rag-responses", "localhost:1")
    with (
        patch(
            "finsentry.archive.restore.consumers_running",
            return_value=["123 python -m finsentry.consumer.main"],
        ),
        pytest.raises(PermissionError, match="consumer is running"),
    ):
        await republish(
            DEFAULT_DIR, "rag-responses", "rag-responses", "localhost:1", allow_live=True
        )
    with pytest.raises(ValueError, match="not an archived topic"):
        await republish(DEFAULT_DIR, "other", "scratch", "localhost:1")
