"""
Write the demo archive: every record of the three streaming topics and every row of the
Red Team and Agent tables, read from where they actually live.

The topics are read straight from Redpanda with no consumer group, so reading commits
nothing and cannot disturb the running consumers. The tables are read in one
REPEATABLE READ transaction so the four of them agree with each other. The files are
deterministic: the same data produces the same bytes, so re-exporting unchanged data
changes nothing in git, and the manifest is only rewritten when a checksum changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from finsentry.archive.format import (
    MANIFEST,
    SCHEMA_VERSION,
    dataset_ids,
    file_entry,
    read_lines,
    stream_line,
)

TOPICS = ("rag-responses", "judge-verdicts", "rag-frontier-verdicts")
# Order matters for a restore: a parent table before the table that references it.
TABLE_ORDER = {
    "red_team_runs": "created_at, run_id",
    "red_team_executions": "run_id, seq",
    "investigations": "created_at, investigation_id",
    "investigation_events": "investigation_id, seq",
}
# The recorded gateway round-trip probe. It is telemetry, not product evidence, and it is not in
# TABLE_ORDER on purpose: a restore would write id 1 without advancing the table's sequence, so the
# next probe run on a restored database would collide. The file is written the same way as the
# tables and is pinned in the manifest as a committed reference, which only the archived-evidence
# site reads.
PROBE_TABLE = "gateway_probe_runs"
PROBE_FILE = f"postgres/{PROBE_TABLE}.jsonl"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "docs" / "demo-archive"

# What the archive does not hold, written into the manifest so nobody has to guess.
OMITTED = [
    "Kafka record headers. None are used.",
    "RisingWave tables and materialized views. They are derived from the three topics and are "
    "rebuilt from them.",
    "The corpus, golden_set and hallucination_bench tables. They are reproducible from public "
    "sources by the ingestion scripts and are not demo evidence.",
    "Original Kafka offsets as a restore target. A replay assigns new offsets. Each record keeps "
    "its original offset and timestamp as data.",
    "Model weights and anything a model produced that no stored event or row carries.",
    "The gateway_probe_runs table as a restore target. Its rows are pinned as a committed "
    "reference for the archived-evidence site and are not restored.",
]


async def _require_single_partition(bootstrap: str, topic: str) -> None:
    """The archive reads partition 0 only, so any other layout must stop the export."""
    from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]

    admin: Any = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        described = await admin.describe_topics([topic])
    finally:
        await admin.close()
    partitions = [p["partition"] for p in described[0]["partitions"]]
    if partitions != [0]:
        raise RuntimeError(f"{topic} has partitions {partitions}, expected only [0]")


async def read_topic(bootstrap: str, topic: str) -> tuple[list[str], list[str], dict[str, object]]:
    """Every record of a one-partition topic, oldest first, as (ids, lines, source)."""
    from aiokafka import AIOKafkaConsumer, TopicPartition  # type: ignore[import-untyped]

    consumer: Any = AIOKafkaConsumer(
        bootstrap_servers=bootstrap, group_id=None, enable_auto_commit=False
    )
    await consumer.start()
    try:
        await _require_single_partition(bootstrap, topic)
        tp = TopicPartition(topic, 0)
        consumer.assign([tp])
        start = (await consumer.beginning_offsets([tp]))[tp]
        end = (await consumer.end_offsets([tp]))[tp]
        consumer.seek(tp, start)
        ids: list[str] = []
        lines: list[str] = []
        while (await consumer.position(tp)) < end:
            batch = await consumer.getmany(tp, timeout_ms=2000, max_records=500)
            for rec in batch.get(tp, []):
                if rec.offset >= end:
                    continue
                key = rec.key.decode() if rec.key is not None else None
                line = stream_line(rec.offset, rec.timestamp, key, json.loads(rec.value))
                lines.append(line)
                ids.append(json.loads(line)["id"])
    finally:
        await consumer.stop()
    source = {"topic": topic, "partition": 0, "log_start_offset": start, "high_watermark": end}
    return ids, lines, source


def read_tables(database_url: str) -> dict[str, list[str]]:
    """Every row of each archived table as the text Postgres makes for to_jsonb(row)."""
    out: dict[str, list[str]] = {}
    with psycopg.connect(database_url) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table, order in TABLE_ORDER.items():
            rows = conn.execute(f"SELECT to_jsonb(t)::text FROM {table} t ORDER BY {order}")  # noqa: S608
            out[table] = [str(r[0]) for r in rows.fetchall()]
    return out


def read_probe_runs(database_url: str) -> list[str]:
    """Every row of gateway_probe_runs as the text Postgres makes for to_jsonb(row). Read only."""
    with psycopg.connect(database_url) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = conn.execute(f"SELECT to_jsonb(t)::text FROM {PROBE_TABLE} t ORDER BY id")  # noqa: S608
        return [str(r[0]) for r in rows.fetchall()]


def _merge(directory: Path, rel: str, name: str, kind: str, fresh: list[str]) -> list[str]:
    """The fresh lines plus any archived line the source no longer has. An export never drops
    a record: a topic that has since expired it, or a row that was deleted, stays archived. A
    row present in both takes the source's current version, so a run that finished since the
    last export is archived as finished."""
    path = directory / rel
    by_id: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                by_id[dataset_ids(name, kind, [json.loads(line)])[0]] = line
    for line in fresh:
        by_id[dataset_ids(name, kind, [json.loads(line)])[0]] = line
    if kind == "stream":
        return sorted(
            by_id.values(),
            key=lambda ln: (json.loads(ln)["timestamp_ms"], json.loads(ln)["offset"]),
        )
    return [by_id[k] for k in sorted(by_id)]


def _write(directory: Path, rel: str, lines: list[str]) -> None:
    path = directory / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


async def export(directory: Path, bootstrap: str, database_url: str) -> dict[str, object]:
    """Write the archive and return its manifest."""
    tables = read_tables(database_url)
    datasets: dict[str, dict[str, object]] = {}
    for topic in TOPICS:
        _, fresh, source = await read_topic(bootstrap, topic)
        rel = f"stream/{topic}.jsonl"
        _write(directory, rel, _merge(directory, rel, topic, "stream", fresh))
        ids = dataset_ids(topic, "stream", read_lines(directory / rel))
        datasets[topic] = file_entry(directory, rel, "stream", ids, source)
    for table, fresh in tables.items():
        rel = f"postgres/{table}.jsonl"
        _write(directory, rel, _merge(directory, rel, table, "table", fresh))
        ids = dataset_ids(table, "table", read_lines(directory / rel))
        datasets[table] = file_entry(
            directory, rel, "table", ids, {"database": "finsentry", "table": table}
        )
    _write(
        directory,
        PROBE_FILE,
        _merge(directory, PROBE_FILE, PROBE_TABLE, "table", read_probe_runs(database_url)),
    )
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": datasets,
        "committed_references": [
            _reference(ROOT / "finsentry" / "redteam" / "scenarios.yml"),
            _reference(ROOT / "docs" / "demo-seed" / "amzn-disagreement-v1.json"),
            _reference(ROOT / "docs" / "demo-seed" / "demo-questions-v1.json"),
            _reference(directory / PROBE_FILE),
        ],
        "omitted": OMITTED,
    }
    existing = directory / MANIFEST
    if existing.is_file():
        previous = json.loads(existing.read_text(encoding="utf-8"))
        if (
            previous.get("datasets") == datasets
            and previous.get("omitted") == OMITTED
            and previous.get("committed_references") == manifest["committed_references"]
        ):
            return previous  # type: ignore[no-any-return]
    existing.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
