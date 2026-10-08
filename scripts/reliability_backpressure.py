#!/usr/bin/env python3
"""Day 9 Scenario C: consumer backpressure, bounded.

Stops the flash-judge consumer, publishes a small burst of constructed events
(copies of one real persisted answer) onto rag-responses, samples the real lag
monitor through the dashboard's /backlog route while the consumer is down,
restarts the consumer, and keeps sampling until the group has caught up. It
then reads the persisted rows back to check that every event produced exactly
one rag_events row and one judge verdict, so nothing was lost.

Lag numbers come from the production ConsumerLagMonitor (rpk group describe),
never from this script's own bookkeeping.

Run with:
    python scripts/reliability_backpressure.py --label as-is --events 16 \\
        --source-trace <real success trace id> \\
        --out docs/measurements/reliability/exp-c-backpressure-as-is.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reliability_experiment import observe, publish_candidates  # noqa: E402

from finsentry.risingwave.dao import risingwave_dsn  # noqa: E402

DASHBOARD = "http://localhost:8081"
CONSUMER_MODULE = "finsentry.consumer.main"


def lag_reading() -> dict[str, Any]:
    body: dict[str, Any] = httpx.get(f"{DASHBOARD}/backlog", timeout=15).json()
    return {
        "at_utc": datetime.now(UTC).isoformat(),
        "total_lag": body.get("total_lag"),
        "end_offset": body["partitions"][0]["end_offset"] if body.get("partitions") else None,
        "committed_offset": body["partitions"][0]["committed_offset"]
        if body.get("partitions")
        else None,
        "monitor_ok": body.get("ok"),
    }


def group_members(group: str) -> int:
    out = subprocess.run(
        ["docker", "exec", "finsentry-redpanda", "rpk", "group", "describe", group],
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout
    for line in out.splitlines():
        if line.startswith("MEMBERS"):
            return int(line.split()[1])
    return 0


def verdict_progress(conn: psycopg.Connection[Any], ids: list[str]) -> int:
    row = conn.execute(
        "SELECT count(DISTINCT app_trace_id) FROM judge_verdicts WHERE app_trace_id = ANY(%s)",
        (ids,),
    ).fetchone()
    return int(row[0]) if row else 0


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--events", type=int, default=16)
    ap.add_argument("--source-trace", required=True)
    ap.add_argument("--down-seconds", type=int, default=24)
    ap.add_argument("--consumer-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    timeline: list[dict[str, Any]] = []
    marks: dict[str, str] = {}

    members_at_start = group_members("finsentry-rag-flash-judge")
    if members_at_start != 1:
        sys.exit(f"flash group has {members_at_start} members; a clean run needs exactly 1")
    baseline = lag_reading()
    print(f"baseline lag: {baseline['total_lag']}, members: {members_at_start}")

    subprocess.run(["pkill", "-TERM", "-f", CONSUMER_MODULE], check=False)
    time.sleep(5)
    marks["consumer_stopped_utc"] = datetime.now(UTC).isoformat()

    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        sent = publish_candidates(conn, args.source_trace, args.events, None)
        ids = [s["app_trace_id"] for s in sent]
        marks["burst_published_utc"] = datetime.now(UTC).isoformat()

        t_end = time.monotonic() + args.down_seconds
        while time.monotonic() < t_end:
            r = lag_reading()
            r.update(phase="consumer_down", verdict_traces=verdict_progress(conn, ids))
            timeline.append(r)
            print(f"  down: lag={r['total_lag']}")
            time.sleep(3)

        with open(args.consumer_log, "w") as log:
            subprocess.Popen(
                [sys.executable, "-m", CONSUMER_MODULE],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
        marks["consumer_restarted_utc"] = datetime.now(UTC).isoformat()

        t_limit = time.monotonic() + 240
        while time.monotonic() < t_limit:
            time.sleep(3)
            r = lag_reading()
            done = verdict_progress(conn, ids)
            r.update(phase="consumer_recovering", verdict_traces=done)
            timeline.append(r)
            print(f"  recovering: lag={r['total_lag']} verdict_traces={done}/{len(ids)}")
            if r["total_lag"] == 0 and done == len(ids):
                marks["caught_up_utc"] = r["at_utc"]
                break
        time.sleep(15)  # catch late duplicate rows before counting
        obs = observe(conn, ids)

    exactly_one_event = sum(1 for o in obs.values() if o["rag_event_rows"] == 1)
    exactly_one_verdict = sum(1 for o in obs.values() if len(o["flash_verdict_rows"]) == 1)
    doc = {
        "experiment": "C",
        "label": args.label,
        "events_published": len(ids),
        "source_trace": args.source_trace,
        "group_members_at_start": members_at_start,
        "group_members_at_end": group_members("finsentry-rag-flash-judge"),
        "baseline_lag": baseline,
        "marks": marks,
        "lag_timeline": timeline,
        "peak_lag_observed": max((t["total_lag"] or 0) for t in timeline),
        "traces_with_exactly_one_rag_event_row": exactly_one_event,
        "traces_with_exactly_one_flash_verdict_row": exactly_one_verdict,
        "caught_up": "caught_up_utc" in marks,
        "trace_ids": ids,
        "flash_verdict_statuses": sorted(
            {v["status"] for o in obs.values() for v in o["flash_verdict_rows"]}
        ),
    }
    Path(args.out).write_text(json.dumps(doc, indent=2, default=str))
    print(
        f"peak lag {doc['peak_lag_observed']}; event rows {exactly_one_event}/{len(ids)}; "
        f"verdict rows {exactly_one_verdict}/{len(ids)}; caught up: {doc['caught_up']}"
    )


if __name__ == "__main__":
    main()
