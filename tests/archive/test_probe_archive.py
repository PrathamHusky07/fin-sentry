"""The recorded gateway probe in the archive: the committed row holds the real stored reading,
the manifest pins the file, and the export reads the table without writing to it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg

from finsentry.archive.export import (
    DEFAULT_DIR,
    PROBE_FILE,
    PROBE_TABLE,
    TABLE_ORDER,
    _merge,
    read_probe_runs,
)
from finsentry.archive.format import MANIFEST, read_lines
from tests.conftest import TEST_DATABASE_URL


def test_the_committed_probe_row_is_the_recorded_reading() -> None:
    rows = read_lines(DEFAULT_DIR / PROBE_FILE)
    assert len(rows) == 1
    row = rows[0]
    # The values read from gateway_probe_runs on 2026-10-25, the run recorded on 2026-10-22.
    assert row["id"] == 1
    assert row["target"] == "http://localhost:8000/health"
    assert row["samples"] == 30
    assert row["median_ms"] == 0.26016650372184813
    assert row["p95_ms"] == 0.35385015944484616
    assert row["max_ms"] == 0.38283399771898985
    assert row["measured_at"] == "2026-10-22T22:28:42.25059+00:00"
    assert isinstance(row["latencies_ms"], list) and len(row["latencies_ms"]) == 30


def test_the_manifest_pins_the_probe_file_and_a_restore_still_skips_it() -> None:
    manifest = json.loads((DEFAULT_DIR / MANIFEST).read_text())
    pinned = {r["path"]: r["sha256"] for r in manifest["committed_references"]}
    path = f"docs/demo-archive/{PROBE_FILE}"
    assert pinned[path] == hashlib.sha256((DEFAULT_DIR / PROBE_FILE).read_bytes()).hexdigest()
    # Not a dataset and not restored: a restore would write id 1 without advancing the sequence.
    assert PROBE_TABLE not in manifest["datasets"]
    assert PROBE_TABLE not in TABLE_ORDER


def test_the_export_reads_probe_rows_as_the_text_postgres_makes_for_them() -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        inserted = conn.execute(
            "INSERT INTO gateway_probe_runs (target, samples, latencies_ms, median_ms, p95_ms,"
            " max_ms) VALUES ('http://probe-archive.test/health', 2, '{1.5, 2.5}', 2.0, 2.5, 2.5)"
            " RETURNING id, to_jsonb(gateway_probe_runs)::text"
        ).fetchone()
        assert inserted is not None
        try:
            lines = read_probe_runs(TEST_DATABASE_URL)
            assert inserted[1] in lines
            # The read is read only: the table still holds the row it held before the read.
            count = conn.execute(
                "SELECT count(*) FROM gateway_probe_runs WHERE id = %s", (inserted[0],)
            ).fetchone()
            assert count is not None and count[0] == 1
        finally:
            conn.execute("DELETE FROM gateway_probe_runs WHERE id = %s", (inserted[0],))


def test_merging_keeps_an_archived_probe_row_the_table_no_longer_has(tmp_path: Path) -> None:
    kept = json.dumps({"id": 1, "median_ms": 0.26})
    (tmp_path / "postgres").mkdir()
    (tmp_path / PROBE_FILE).write_text(kept + "\n", encoding="utf-8")
    fresh = [json.dumps({"id": 2, "median_ms": 0.31})]
    merged = _merge(tmp_path, PROBE_FILE, PROBE_TABLE, "table", fresh)
    assert [json.loads(line)["id"] for line in merged] == [1, 2]
