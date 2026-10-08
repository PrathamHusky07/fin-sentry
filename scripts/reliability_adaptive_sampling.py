#!/usr/bin/env python3
"""Day 9 adaptive frontier sampling, run live and bounded.

Restarts the frontier consumer with low lag thresholds (the spec default of
1000 pending events is out of reach for a bounded run), publishes a burst of
constructed events whose real sampling hash says "sampled at the normal rate",
and watches the consumer's own log for the rate change while the real lag
monitor reports the backlog. Once the backlog has drained and the rate has
recovered, it publishes a small probe set and checks that the normal rate is
back in force.

Everything recorded is read from the real stack: lag from ConsumerLagMonitor,
rate changes from the consumer's log lines, evaluations from persisted
rag_frontier_verdicts rows.

Run with:
    python scripts/reliability_adaptive_sampling.py --burst 30 --probe 6 \\
        --source-trace <real success trace id> --consumer-log <path> \\
        --out docs/measurements/reliability/exp-d-adaptive-sampling.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reliability_backpressure import group_members  # noqa: E402
from reliability_experiment import publish_candidates  # noqa: E402

from finsentry.consumer.lag_monitor import ConsumerLagMonitor  # noqa: E402
from finsentry.frontier.sampling import should_sample_for_frontier  # noqa: E402
from finsentry.risingwave.dao import risingwave_dsn  # noqa: E402

MODULE = "finsentry.consumer.frontier_consumer"
GROUP = "frontier-tier"
RATE_LINE = re.compile(r"frontier sampling rate 1/(\d+) -> 1/(\d+): (.*)")


def frontier_rows(conn: psycopg.Connection[Any], ids: list[str]) -> int:
    row = conn.execute(
        "SELECT count(DISTINCT app_trace_id) FROM rag_frontier_verdicts "
        "WHERE app_trace_id = ANY(%s)",
        (ids,),
    ).fetchone()
    return int(row[0]) if row else 0


def rate_changes(log_path: Path) -> list[dict[str, Any]]:
    out = []
    for line in log_path.read_text(errors="replace").splitlines():
        m = RATE_LINE.search(line)
        if m:
            out.append({"from": int(m[1]), "to": int(m[2]), "reason_and_lag": m[3]})
    return out


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--burst", type=int, default=30)
    ap.add_argument("--probe", type=int, default=6)
    ap.add_argument("--entry-lag", type=int, default=8)
    ap.add_argument("--recovery-lag", type=int, default=2)
    ap.add_argument("--source-trace", required=True)
    ap.add_argument("--consumer-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    log_path = Path(args.consumer_log)
    monitor = ConsumerLagMonitor(group_id=GROUP, topic="rag-responses")

    subprocess.run(["pkill", "-TERM", "-f", MODULE], check=False)
    time.sleep(5)
    env = {
        **os.environ,
        "FRONTIER_LAG_ENTRY_THRESHOLD": str(args.entry_lag),
        "FRONTIER_LAG_RECOVERY_THRESHOLD": str(args.recovery_lag),
    }
    with open(log_path, "w") as log:
        subprocess.Popen(
            [sys.executable, "-m", MODULE],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    members = 0
    for _ in range(30):  # the consumer loads an embedding model before it joins
        time.sleep(3)
        members = group_members(GROUP)
        if members:
            break
    if members != 1:
        sys.exit(f"frontier group has {members} members; a clean run needs exactly 1")

    timeline: list[dict[str, Any]] = []
    seen_changes = 0

    def sample(phase: str, ids: list[str], conn: psycopg.Connection[Any]) -> dict[str, Any]:
        nonlocal seen_changes
        report = monitor._fetch_lag_blocking()
        changes = rate_changes(log_path)
        point = {
            "at_utc": datetime.now(UTC).isoformat(),
            "phase": phase,
            "lag": report.total_lag if report.ok else None,
            "evaluated_traces": frontier_rows(conn, ids),
            "rate_changes_in_log": len(changes),
        }
        if len(changes) > seen_changes:
            point["new_rate_change"] = changes[seen_changes:]
            seen_changes = len(changes)
        timeline.append(point)
        print(f"  {phase}: lag={point['lag']} evaluated={point['evaluated_traces']}", end="")
        print(f" rate_changes={point['rate_changes_in_log']}")
        return point

    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        burst = publish_candidates(conn, args.source_trace, args.burst, True)
        burst_ids = [b["app_trace_id"] for b in burst]
        burst_at_reduced = sum(should_sample_for_frontier(t, 100) for t in burst_ids)
        published_at = datetime.now(UTC).isoformat()

        deadline = time.monotonic() + 240
        stable = 0
        last_eval = -1
        while time.monotonic() < deadline:
            p = sample("burst", burst_ids, conn)
            drained = p["lag"] == 0
            same = p["evaluated_traces"] == last_eval
            last_eval = p["evaluated_traces"]
            stable = stable + 1 if (drained and same) else 0
            if stable >= 6 and len(rate_changes(log_path)) >= 2:
                break
            time.sleep(3)

        probe = publish_candidates(conn, args.source_trace, args.probe, True)
        probe_ids = [b["app_trace_id"] for b in probe]
        time.sleep(1)
        probe_deadline = time.monotonic() + 90
        while time.monotonic() < probe_deadline:
            p = sample("probe", probe_ids, conn)
            if p["evaluated_traces"] == len(probe_ids):
                break
            time.sleep(4)
        burst_evaluated = frontier_rows(conn, burst_ids)
        probe_evaluated = frontier_rows(conn, probe_ids)

    doc = {
        "experiment": "D",
        "published_burst_at_utc": published_at,
        "thresholds": {"entry_lag": args.entry_lag, "recovery_lag": args.recovery_lag},
        "defaults_from_spec": {"entry_lag": 1000, "recovery_lag": 200},
        "group_members": members,
        "burst_events": len(burst_ids),
        "burst_events_hash_sampled_at_normal_rate": len(burst_ids),
        "burst_events_hash_sampled_at_reduced_rate": burst_at_reduced,
        "burst_events_evaluated_by_frontier": burst_evaluated,
        "rate_changes_logged_by_consumer": rate_changes(log_path),
        "probe_events": len(probe_ids),
        "probe_events_evaluated_by_frontier": probe_evaluated,
        "timeline": timeline,
        "burst_trace_ids": burst_ids,
        "probe_trace_ids": probe_ids,
    }
    Path(args.out).write_text(json.dumps(doc, indent=2, default=str))
    print(
        f"burst {len(burst_ids)}: evaluated {burst_evaluated}, "
        f"reduced-rate expected {burst_at_reduced}; probe {probe_evaluated}/{len(probe_ids)}; "
        f"rate changes {len(doc['rate_changes_logged_by_consumer'])}"
    )


if __name__ == "__main__":
    main()
