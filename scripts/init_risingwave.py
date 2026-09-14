#!/usr/bin/env python3
"""Initialize RisingWave sources and materialized views.

Reads infra/risingwave/init.sql and executes each statement against
the RisingWave instance at RISINGWAVE_HOST:RISINGWAVE_PORT.

Usage:
    python scripts/init_risingwave.py
    python scripts/init_risingwave.py --dry-run

Environment variables:
    RISINGWAVE_HOST   (default: localhost)
    RISINGWAVE_PORT   (default: 4566)
    RISINGWAVE_USER   (default: root)
    RISINGWAVE_DB     (default: dev)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

from finsentry.events.topics import JUDGE_VERDICTS_TOPIC, RAG_RESPONSES_TOPIC

_SQL_PATH = pathlib.Path(__file__).parent.parent / "infra" / "risingwave" / "init.sql"


def _split_statements(sql: str) -> list[str]:
    """Split SQL text on statement-ending semicolons, ignoring semicolons inside
    -- line comments and /* */ block comments. Empty and comment-only chunks
    are dropped. Preserves comments inside the returned statements for context."""
    stripped_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    stripped_line = re.sub(r"--[^\n]*", "", stripped_block)
    parts = stripped_line.split(";")
    return [p.strip() for p in parts if p.strip()]


def _ensure_topics(topic_names: list[str]) -> None:
    """Ensure Kafka topics exist in the Redpanda container via rpk.

    rpk exits non-zero for both failures and already-exists. The already-exists
    marker appears in stdout in current rpk versions (not stderr), so both
    streams are checked case-insensitively to survive future rpk output drift.
    """
    print(f"[topic-check] Ensuring topics exist: {', '.join(topic_names)}")
    for topic in topic_names:
        result = subprocess.run(
            ["docker", "exec", "finsentry-redpanda", "rpk", "topic", "create", topic],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # rpk writes the "already exists" status to stdout and exits non-zero.
        # Check both streams case-insensitively so future rpk versions that
        # change output stream or casing don't regress this path.
        combined = ((result.stdout or "") + (result.stderr or "")).upper()
        already_exists = "TOPIC_ALREADY_EXISTS" in combined or "ALREADY BEEN CREATED" in combined
        if result.returncode != 0 and not already_exists:
            raise RuntimeError(
                f"Failed to ensure topic {topic!r}: "
                f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            )
    print("[topic-check] OK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize RisingWave sources and views")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    args = parser.parse_args(argv)

    if not args.dry_run:
        _ensure_topics([RAG_RESPONSES_TOPIC, JUDGE_VERDICTS_TOPIC])

    sql = _SQL_PATH.read_text()
    statements = _split_statements(sql)

    host = os.getenv("RISINGWAVE_HOST", "localhost")
    port = int(os.getenv("RISINGWAVE_PORT", "4566"))
    user = os.getenv("RISINGWAVE_USER", "root")
    db = os.getenv("RISINGWAVE_DB", "dev")

    if args.dry_run:
        for i, stmt in enumerate(statements, 1):
            print(f"-- Statement {i} --")
            print(stmt)
            print()
        print(f"Dry run: {len(statements)} statements would be executed against {host}:{port}/{db}")
        return 0

    try:
        import psycopg  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: psycopg not installed. Run: pip install 'psycopg[binary]'", file=sys.stderr)
        return 1

    conninfo = f"host={host} port={port} user={user} dbname={db}"
    try:
        conn = psycopg.connect(conninfo, autocommit=True)
    except Exception as exc:
        print(f"ERROR: Could not connect to RisingWave at {host}:{port} — {exc}", file=sys.stderr)
        return 1

    with conn.cursor() as cur:
        for i, stmt in enumerate(statements, 1):
            preview = stmt[:60].replace("\n", " ")
            print(f"[{i}/{len(statements)}] {preview}...")
            try:
                cur.execute(stmt)
                print(f"  OK")
            except Exception as exc:
                print(f"  ERROR: {exc}", file=sys.stderr)
                conn.close()
                return 1

    conn.close()
    print(f"\nDone — {len(statements)} statements executed against {host}:{port}/{db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
