"""Infrastructure helpers for scripts/load_test.py: processes, rpk, topics, RisingWave.

Nothing here touches the live topics or tables. The load test owns two topics and two
RisingWave tables of its own, created at setup and removed at teardown.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from load_test_lib import parse_group_describe

from finsentry.risingwave.dao import risingwave_dsn

ROOT = Path(__file__).resolve().parent.parent
REDPANDA = "finsentry-redpanda"
BOOTSTRAP = "localhost:19092"  # host listener; RisingWave reaches the broker as redpanda:9092

EVENTS_TOPIC = "lt-rag-responses"
VERDICTS_TOPIC = "lt-judge-verdicts"
GROUP = "lt-flash"
EVENTS_TABLE = "lt_rag_events"
VERDICTS_TABLE = "lt_judge_verdicts"

_TABLE_OPTIONS = (
    "WITH (connector='kafka', topic='{topic}', properties.bootstrap.server='redpanda:9092',"
    " scan.startup.mode='earliest') FORMAT PLAIN ENCODE JSON"
)
_TABLES = {
    EVENTS_TABLE: (
        "event_id VARCHAR, app_trace_id VARCHAR, timestamp_utc TIMESTAMPTZ, status VARCHAR,"
        " query VARCHAR, total_latency_ms INT, block_rail VARCHAR, error_kind VARCHAR",
        EVENTS_TOPIC,
    ),
    VERDICTS_TABLE: (
        "event_id VARCHAR, source_event_id VARCHAR, app_trace_id VARCHAR,"
        " faithfulness_status VARCHAR, total_gemini_calls INT, status VARCHAR,"
        " evaluation_latency_ms INT",
        VERDICTS_TOPIC,
    ),
}


def rpk(*args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["docker", "exec", REDPANDA, "rpk", *args], capture_output=True, text=True, timeout=60
    )
    if check and done.returncode != 0:
        raise RuntimeError(f"rpk {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def group_state(group: str = GROUP) -> dict[str, Any]:
    return parse_group_describe(rpk("group", "describe", group, check=False))


def high_watermark(topic: str) -> int:
    """Messages ever written to a single-partition topic."""
    for line in rpk("topic", "describe", topic, "-p").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit():
            return int(parts[-1])
    raise RuntimeError(f"no partition row for {topic}")


def active_groups() -> list[str]:
    """Consumer groups with a live member, other than the load test's own."""
    names = []
    for line in rpk("group", "list").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[2] != "Empty" and parts[1] != GROUP:
            names.append(parts[1])
    return names


def create_topics() -> None:
    for topic in (EVENTS_TOPIC, VERDICTS_TOPIC):
        rpk("topic", "create", topic, "-p", "1", "-r", "1")


def create_tables() -> None:
    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        for name, (columns, topic) in _TABLES.items():
            conn.execute(f"CREATE TABLE {name} ({columns}) {_TABLE_OPTIONS.format(topic=topic)}")


def risingwave_rows(sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        conn.execute("FLUSH")
        return [tuple(r) for r in conn.execute(sql).fetchall()]


def teardown_infra() -> dict[str, str]:
    """Remove everything the load test created. Each step is attempted regardless of
    the others, and the outcome of each is returned for the record."""
    done: dict[str, str] = {}
    try:
        with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
            for name in _TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {name}")
        done["risingwave_tables"] = "dropped"
    except Exception as exc:
        done["risingwave_tables"] = f"failed: {type(exc).__name__}"
    done["consumer_group"] = rpk("group", "delete", GROUP, check=False).strip()[:80] or "absent"
    for topic in (EVENTS_TOPIC, VERDICTS_TOPIC):
        done[topic] = rpk("topic", "delete", topic, check=False).strip()[:80] or "absent"
    return done


@dataclass
class Proc:
    name: str
    popen: subprocess.Popen[bytes]
    log: Path

    def alive(self) -> bool:
        return self.popen.poll() is None

    def log_tail(self, lines: int = 15) -> str:
        return "\n".join(self.log.read_text(errors="replace").splitlines()[-lines:])


def spawn(name: str, argv: list[str], log_dir: Path) -> Proc:
    log = log_dir / f"{name}.log"
    handle = open(log, "wb")
    popen = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "load_test_stack.py"), *argv],
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
        start_new_session=True,
    )
    return Proc(name, popen, log)


def stop(proc: Proc, grace_s: float = 25.0) -> None:
    if not proc.alive():
        return
    proc.popen.send_signal(signal.SIGTERM)
    try:
        proc.popen.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.popen.kill()
        proc.popen.wait(timeout=10)


def wait_for_file(path: Path, proc: Proc, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        if not proc.alive():
            raise RuntimeError(f"{proc.name} exited before it attested:\n{proc.log_tail()}")
        time.sleep(1.0)
    raise RuntimeError(f"{proc.name} did not attest within {timeout_s:g}s:\n{proc.log_tail()}")


def process_usage(pid: int) -> dict[str, float] | None:
    out = subprocess.run(
        ["ps", "-o", "%cpu=,rss=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.split()
    return {"cpu_pct": float(out[0]), "rss_mb": round(int(out[1]) / 1024, 1)} if out else None


def docker_usage() -> dict[str, dict[str, str]]:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    return {r["Name"]: {"cpu": r["CPUPerc"], "mem": r["MemUsage"]} for r in rows}


async def read_topic(topic: str) -> list[dict[str, Any]]:
    """Every message currently in a topic, decoded as JSON. Read without a group, so
    it never joins or disturbs the consumer under test."""
    from aiokafka import AIOKafkaConsumer, TopicPartition

    consumer = AIOKafkaConsumer(
        bootstrap_servers=BOOTSTRAP, group_id=None, enable_auto_commit=False
    )
    await consumer.start()
    try:
        tp = TopicPartition(topic, 0)
        consumer.assign([tp])
        await consumer.seek_to_beginning(tp)
        end = (await consumer.end_offsets([tp]))[tp]
        messages: list[dict[str, Any]] = []
        while await consumer.position(tp) < end:
            batch = await consumer.getmany(tp, timeout_ms=2000, max_records=500)
            messages.extend(json.loads(m.value) for m in batch.get(tp, []))
        return messages
    finally:
        await consumer.stop()
