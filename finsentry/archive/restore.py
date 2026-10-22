"""
Read the demo archive back into Postgres, or back into a topic, without rerunning RAG.

materialize() writes the archive into durable Postgres tables. It is idempotent by
construction: every insert is ON CONFLICT DO NOTHING on the record's own identity, so a
second run adds nothing and a record that already exists, finished or not, is never
overwritten. It refuses to run if the archive does not verify.

republish() puts archived stream records back on a topic. A live topic has consumers that
call Gemini for every event on rag-responses, so a live target needs an explicit flag and
no running consumer process.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import psycopg

from finsentry.archive.export import TABLE_ORDER, TOPICS
from finsentry.archive.format import read_lines, verify_archive

LIVE_TOPICS = frozenset(TOPICS)


class ArchiveInvalidError(RuntimeError):
    """The archive failed verification, so nothing was written."""


def materialize(directory: Path, database_url: str) -> dict[str, int]:
    """Load the archive into Postgres. Returns how many records each dataset inserted."""
    problems = verify_archive(directory)
    if problems:
        raise ArchiveInvalidError("; ".join(problems))
    inserted: dict[str, int] = {}
    with psycopg.connect(database_url) as conn:
        for topic in TOPICS:
            count = 0
            for rec in read_lines(directory / "stream" / f"{topic}.jsonl"):
                cur = conn.execute(
                    "INSERT INTO stream_archive (topic, record_sha256, source_offset, record_key,"
                    " record_timestamp, value) VALUES (%s, %s, %s, %s, to_timestamp(%s / 1000.0),"
                    " %s::jsonb) ON CONFLICT DO NOTHING",
                    (
                        topic,
                        rec["id"],
                        rec["offset"],
                        rec["key"],
                        rec["timestamp_ms"],
                        json.dumps(rec["value"]),
                    ),
                )
                count += cur.rowcount
            inserted[topic] = count
        for table in TABLE_ORDER:
            count = 0
            for line in (directory / "postgres" / f"{table}.jsonl").read_text("utf-8").splitlines():
                cur = conn.execute(
                    f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, "  # noqa: S608
                    "%s::jsonb) ON CONFLICT DO NOTHING",
                    (line,),
                )
                count += cur.rowcount
            inserted[table] = count
        conn.commit()
    return inserted


def consumers_running() -> list[str]:
    """The command lines of any running finsentry consumer process."""
    out = subprocess.run(["pgrep", "-fl", "finsentry.consumer"], capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


async def republish(
    directory: Path, topic: str, target: str, bootstrap: str, allow_live: bool = False
) -> int:
    """Publish the archived records of `topic` to `target`. Returns the count published."""
    if topic not in LIVE_TOPICS:
        raise ValueError(f"{topic} is not an archived topic")
    if target in LIVE_TOPICS:
        if not allow_live:
            raise PermissionError(f"{target} is a live topic. Pass allow_live to publish to it.")
        running = consumers_running()
        if running:
            raise PermissionError(
                "a consumer is running and would judge every replayed event: " + "; ".join(running)
            )
    problems = verify_archive(directory)
    if problems:
        raise ArchiveInvalidError("; ".join(problems))
    from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

    producer: Any = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        records = read_lines(directory / "stream" / f"{topic}.jsonl")
        for rec in records:
            key = rec["key"].encode() if isinstance(rec["key"], str) else None
            await producer.send_and_wait(
                target, json.dumps(rec["value"]).encode(), key=key, timestamp_ms=rec["timestamp_ms"]
            )
    finally:
        await producer.stop()
    return len(records)
