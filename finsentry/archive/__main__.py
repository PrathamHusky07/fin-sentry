"""
python -m finsentry.archive <command>

    export       write docs/demo-archive from the live topics and tables (read only; merges
                 with an existing archive and never drops a record)
    verify       read the archive back with no network: checksums, counts, ids
    reconcile    compare the archive with the live topics, RisingWave and Postgres
    materialize  load the archive into Postgres (stream_archive plus the Red Team and Agent
                 tables), idempotent, never overwrites an existing row
    republish    put archived stream records back on a topic; a live topic needs --allow-live
                 and no running consumer
    coverage     the RAG coverage matrix, read only
    fill         ask the missing questions through the real gateway, one at a time, with a
                 memory check and a preventive spend cap before each request (--dry-run
                 prints the plan and asks nothing)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from finsentry.archive import coverage
from finsentry.archive.export import DEFAULT_DIR, export
from finsentry.archive.format import verify_archive
from finsentry.archive.reconcile import reconcile
from finsentry.archive.restore import materialize, republish


def _bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="finsentry.archive", description=__doc__)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("export", "verify", "reconcile", "materialize", "coverage"):
        sub.add_parser(name)
    fp = sub.add_parser("fill")
    fp.add_argument("--budget", type=float, required=True, help="Gemini spend cap in USD")
    fp.add_argument("--limit", type=int, default=100, help="most requests to send")
    fp.add_argument("--spent", type=float, default=0.0, help="USD already spent against the cap")
    fp.add_argument("--dry-run", action="store_true")
    rp = sub.add_parser("republish")
    rp.add_argument("--topic", required=True)
    rp.add_argument("--into", required=True)
    rp.add_argument("--allow-live", action="store_true")
    args = ap.parse_args()
    db = os.environ["DATABASE_URL"]

    if args.command == "export":
        manifest = asyncio.run(export(args.dir, _bootstrap(), db))
        for name, entry in manifest["datasets"].items():  # type: ignore[attr-defined]
            print(f"{name}: {entry['records']} records, sha256 {entry['sha256'][:12]}")
    elif args.command == "verify":
        problems = verify_archive(args.dir)
        print("archive verifies" if not problems else "\n".join(problems))
        return 1 if problems else 0
    elif args.command == "reconcile":
        problems = asyncio.run(reconcile(args.dir, _bootstrap(), db))
        print("reconciles" if not problems else "\n".join(problems))
        return 1 if problems else 0
    elif args.command == "materialize":
        for name, count in materialize(args.dir, db).items():
            print(f"{name}: {count} inserted")
    elif args.command == "republish":
        n = asyncio.run(
            republish(args.dir, args.topic, args.into, _bootstrap(), allow_live=args.allow_live)
        )
        print(f"published {n} records to {args.into}")
    elif args.command == "fill":
        from finsentry.archive import fill

        fill.main(args.budget, args.limit, args.dry_run, args.spent)
    else:
        rows = coverage.matrix(coverage.load_stored(), coverage.archived_event_ids(args.dir))
        print(coverage.render(rows))
        print(coverage.per_company(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
