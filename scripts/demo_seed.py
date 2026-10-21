#!/usr/bin/env python3
"""Keep the demo data from silently disappearing, and rebuild the demo questions on request.

Root cause this guards against. RisingWave's three sources read the Redpanda topics, so a trace
exists only while its Kafka records do. The topics default to 7-day retention, and the AMZN
disagreement trace (2026-10-03) and the Day 9 corpus (2026-10-06) expired from them. Nothing
was wrong with RisingWave itself.

Commands, all safe to run twice:
    python scripts/demo_seed.py status      read only: which seed questions have a stored
                                            execution, whether the AMZN trace exists, and the
                                            retention of each topic
    python scripts/demo_seed.py retention   set retention.ms=-1 on the three topics
    python scripts/demo_seed.py send --limit 1
                                            ask the first missing seed questions through the
                                            real gateway, one at a time, only while memory is
                                            free. Each answer is real pipeline output and
                                            costs real judge calls. A question that already
                                            has a stored execution is never asked again.

The seed lives in docs/demo-seed/. The AMZN trace cannot be replayed: a trace id is minted by
the gateway, so a new run is a new trace. Its recovered fields are kept as a HISTORICAL record.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.risingwave.dao import risingwave_dsn

SEED_DIR = Path(__file__).resolve().parent.parent / "docs" / "demo-seed"
GATEWAY = "http://localhost:8000"
TOPICS = ("rag-responses", "judge-verdicts", "rag-frontier-verdicts")
BROKER = "finsentry-redpanda"
MIN_FREE_MEMORY_PERCENT = 25  # below this, send stops. A past RAG run crashed this machine.


def load_questions() -> list[dict[str, str]]:
    seed = json.loads((SEED_DIR / "demo-questions-v1.json").read_text())
    questions: list[dict[str, str]] = seed["questions"]
    return questions


def missing_questions(
    questions: list[dict[str, str]], stored: set[tuple[str, str]]
) -> list[dict[str, str]]:
    """The seed questions with no stored execution. An execution of any outcome counts, so a
    blocked answer is not asked again to find a nicer one."""
    return [q for q in questions if (q["ticker"], q["query"]) not in stored]


def free_memory_percent(memory_pressure_output: str) -> int:
    """Parse `memory_pressure -Q` ("System-wide memory free percentage: 41%")."""
    found = re.search(r"free percentage:\s*(\d+)%", memory_pressure_output)
    if not found:
        raise ValueError("could not read the free memory percentage")
    return int(found.group(1))


def retention_is_unbounded(describe_config_output: str) -> bool:
    for line in describe_config_output.splitlines():
        parts = line.split()
        if parts and parts[0] == "retention.ms":
            return parts[1] == "-1"
    return False


def _rpk(*args: str) -> str:
    done = subprocess.run(
        ["docker", "exec", BROKER, "rpk", *args], capture_output=True, text=True, check=True
    )
    return done.stdout


def _stored_pairs() -> set[tuple[str, str]]:
    with psycopg.connect(risingwave_dsn()) as conn:
        rows = conn.execute("SELECT DISTINCT ticker, query FROM rag_events").fetchall()
    return {(str(t), str(q)) for t, q in rows}


def _trace_exists(trace_id: str) -> bool:
    with psycopg.connect(risingwave_dsn()) as conn:
        row: Any = conn.execute(
            "SELECT count(*) FROM rag_events WHERE app_trace_id = %s", (trace_id,)
        ).fetchone()
    return bool(row[0])


def status() -> None:
    questions = load_questions()
    missing = missing_questions(questions, _stored_pairs())
    print(
        f"seed questions with a stored execution: {len(questions) - len(missing)}/{len(questions)}"
    )
    for q in missing:
        print(f"  missing  {q['id']}")
    amzn = json.loads((SEED_DIR / "amzn-disagreement-v1.json").read_text())
    present = _trace_exists(amzn["app_trace_id"])
    print(f"AMZN disagreement trace {amzn['app_trace_id']}: {'present' if present else 'absent'}")
    for topic in TOPICS:
        unbounded = retention_is_unbounded(_rpk("topic", "describe", topic, "-c"))
        print(f"topic {topic}: retention {'unbounded' if unbounded else 'time-limited'}")


def retention() -> None:
    for topic in TOPICS:
        if retention_is_unbounded(_rpk("topic", "describe", topic, "-c")):
            print(f"{topic}: already unbounded")
            continue
        _rpk("topic", "alter-config", topic, "--set", "retention.ms=-1")
        print(f"{topic}: retention.ms set to -1")


def send(limit: int) -> None:
    todo = missing_questions(load_questions(), _stored_pairs())[:limit]
    with httpx.Client(timeout=200.0) as client:
        for q in todo:
            free = free_memory_percent(
                subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True).stdout
            )
            if free < MIN_FREE_MEMORY_PERCENT:
                print(f"stopping: {free}% memory free, below {MIN_FREE_MEMORY_PERCENT}%")
                return
            resp = client.post(
                f"{GATEWAY}/v1/rag/query", json={"query": q["query"], "ticker": q["ticker"]}
            )
            print(f"{q['id']}: http {resp.status_code}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("retention")
    sp = sub.add_parser("send")
    sp.add_argument("--limit", type=int, required=True, help="how many missing questions to ask")
    args = ap.parse_args()
    if args.command == "status":
        status()
    elif args.command == "retention":
        retention()
    else:
        send(args.limit)


if __name__ == "__main__":
    main()
