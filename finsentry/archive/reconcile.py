"""
Check the archive against the sources it was taken from: counts, stable ids and content
checksums, topic by topic and table by table. This is the read-only proof that an export
holds what is actually stored, and that the live query layer agrees with both.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg

from finsentry.archive.export import TABLE_ORDER, TOPICS, read_tables, read_topic
from finsentry.archive.format import dataset_ids, read_lines
from finsentry.risingwave.dao import risingwave_dsn

RISINGWAVE_SOURCES = {
    "rag-responses": "rag_events",
    "judge-verdicts": "judge_verdicts",
    "rag-frontier-verdicts": "rag_frontier_verdicts",
}


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


async def reconcile(directory: Path, bootstrap: str, database_url: str) -> list[str]:
    """Mismatches between the archive and the live sources. Empty means they reconcile: every
    live record is archived with identical content, and the counts agree."""
    problems: list[str] = []
    with psycopg.connect(risingwave_dsn()) as rw:
        for topic in TOPICS:
            _, live_lines, source = await read_topic(bootstrap, topic)
            archived = {r["id"]: r for r in read_lines(directory / "stream" / f"{topic}.jsonl")}
            live = {r["id"]: r for r in (json.loads(ln) for ln in live_lines)}
            absent = sorted(set(live) - set(archived))
            if absent:
                problems.append(f"{topic}: {len(absent)} live records are not archived")
            drifted = [
                i for i in live if i in archived and archived[i]["value"] != live[i]["value"]
            ]
            if drifted:
                problems.append(f"{topic}: {len(drifted)} archived records differ from the topic")
            rw_count = rw.execute(f"SELECT count(*) FROM {RISINGWAVE_SOURCES[topic]}").fetchone()  # noqa: S608
            if rw_count is None or int(rw_count[0]) != len(live):
                problems.append(f"{topic}: RisingWave has {rw_count}, the topic has {len(live)}")
            print(
                f"{topic}: topic {len(live)} (offsets {source['log_start_offset']}.."
                f"{source['high_watermark']}), archive {len(archived)}, RisingWave "
                f"{rw_count[0] if rw_count else '?'}"
            )
    live_tables = read_tables(database_url)
    for table in TABLE_ORDER:
        archived_lines = (directory / "postgres" / f"{table}.jsonl").read_text("utf-8").splitlines()
        live_ids = set(dataset_ids(table, "table", [json.loads(x) for x in live_tables[table]]))
        arch_ids = set(dataset_ids(table, "table", [json.loads(x) for x in archived_lines]))
        if live_ids - arch_ids:
            problems.append(f"{table}: {len(live_ids - arch_ids)} live rows are not archived")
        if set(live_tables[table]) - set(archived_lines):
            problems.append(f"{table}: some live rows differ from their archived version")
        live_set = set(live_tables[table])
        matched = [x for x in archived_lines if x in live_set]
        print(
            f"{table}: live {len(live_ids)}, archive {len(arch_ids)}, "
            f"live digest {_digest(live_tables[table])[:12]}, "
            f"archive digest of the same rows {_digest(matched)[:12]}"
        )
    return problems
