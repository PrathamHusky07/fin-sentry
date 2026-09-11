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
import sys

_SQL_PATH = pathlib.Path(__file__).parent.parent / "infra" / "risingwave" / "init.sql"


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons, skip blank lines and pure comments."""
    parts = sql.split(";")
    statements = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        non_comment = "\n".join(
            line for line in stripped.splitlines()
            if not line.strip().startswith("--")
        ).strip()
        if non_comment:
            statements.append(stripped)
    return statements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize RisingWave sources and views")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    args = parser.parse_args(argv)

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
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        return 1

    try:
        conn = psycopg2.connect(host=host, port=port, user=user, dbname=db)
        conn.autocommit = True
    except Exception as exc:
        print(f"ERROR: Could not connect to RisingWave at {host}:{port} — {exc}", file=sys.stderr)
        return 1

    with conn.cursor() as cur:
        for i, stmt in enumerate(statements, 1):
            first_line = stmt.splitlines()[0][:80]
            print(f"[{i}/{len(statements)}] {first_line}...")
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
