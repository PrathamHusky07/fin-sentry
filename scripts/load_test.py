#!/usr/bin/env python3
"""Day 10C bounded, staged load test of the gateway with every rail enabled.

Runs its own isolated pipeline (stub downstream, gateway on :8010, flash consumer, two
topics, two RisingWave tables) so the live topics and dashboards are never touched and no
Gemini call can happen. The harness refuses to generate load unless the isolation
attestations pass. It then offers load in stages at a fixed arrival rate, checks the
machine between and during stages, and stops at the first stage that breaks the SLO or
the resource limits. Offered load and achieved throughput are reported separately.

    python scripts/load_test.py                       # the full staged run
    python scripts/load_test.py --stages 0.5:10 --out /tmp/smoke.json   # harness smoke run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_test_io import (  # noqa: E402
    BOOTSTRAP,
    EVENTS_TOPIC,
    GROUP,
    ROOT,
    VERDICTS_TOPIC,
    Proc,
    active_groups,
    create_tables,
    create_topics,
    docker_usage,
    group_state,
    high_watermark,
    process_usage,
    spawn,
    stop,
    teardown_infra,
    wait_for_file,
)
from load_test_lib import (  # noqa: E402
    Record,
    ResourceLimits,
    Slo,
    arrival_offsets,
    consumer_attestation_problems,
    gateway_attestation_problems,
    has_headroom,
    read_resources,
    resource_breach,
    slo_violations,
    stage_stats,
)
from load_test_report import collect_legs, finish_summary  # noqa: E402
from reliability_experiment import QUESTIONS  # noqa: E402

GATEWAY_PORT, STUB_PORT = 8010, 8011
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"
STUB_URL = f"http://127.0.0.1:{STUB_PORT}"
DEFAULT_STAGES = "0.5:60,1:60,2:60,3:60,4:60,6:60,8:60,12:60,16.67:60"
MAX_IN_FLIGHT = 256
SAMPLE_EVERY_S = 3.0
TARGET_RPS = 16.0  # the 1,000 requests/minute target stage starts at this rate
SLO, LIMITS = Slo(), ResourceLimits()


class IsolationError(RuntimeError):
    """The isolation checks failed. No load was generated."""


class Run:
    def __init__(self, raw: Path) -> None:
        self.raw = raw
        self.seq = 0
        self.stage = "setup"
        self.abort: str | None = None
        self.samples: list[dict[str, Any]] = []
        self.responses: list[tuple[str | None, int | None]] = []
        self.baseline: dict[str, float] = {}
        self.stop_sampler = threading.Event()
        self.gateway_pid = 0
        self.gateway: Proc | None = None

    def next_request(self) -> tuple[int, str, str]:
        seq = self.seq
        self.seq += 1
        ticker, question = QUESTIONS[seq % len(QUESTIONS)]
        return seq, ticker, question


def sampler(run: Run) -> None:
    while not run.stop_sampler.wait(SAMPLE_EVERY_S):
        try:
            res = read_resources()
            usage = process_usage(run.gateway_pid) or {}
            run.samples.append(
                {
                    "t": time.time(),
                    "stage": run.stage,
                    **res,
                    "consumer_lag": group_state()["total_lag"],
                    "gateway_cpu_pct": usage.get("cpu_pct"),
                    "gateway_rss_mb": usage.get("rss_mb"),
                }
            )
            if run.gateway is not None and not run.gateway.alive() and run.abort is None:
                run.abort = f"gateway process exited with code {run.gateway.popen.returncode}"
            breach = resource_breach(res, run.baseline, LIMITS)
            if breach and run.abort is None:
                run.abort = f"resource limit: {breach}"
        except Exception as exc:  # a failed reading must not end the load test
            run.samples.append({"t": time.time(), "stage": run.stage, "error": repr(exc)})


def verify_isolation(gateway_att: dict[str, Any], consumer_att: dict[str, Any]) -> dict[str, Any]:
    gateway_expect = {"stub_url": STUB_URL, "topic": EVENTS_TOPIC}
    consumer_expect = {"topic": EVENTS_TOPIC, "group": GROUP, "verdict_topic": VERDICTS_TOPIC}
    problems = [f"gateway: {p}" for p in gateway_attestation_problems(gateway_att, gateway_expect)]
    problems += [
        f"consumer: {p}" for p in consumer_attestation_problems(consumer_att, consumer_expect)
    ]
    others: dict[str, list[str]] = {}
    for name in active_groups():
        others[name] = group_state(name)["topics"]
        if {EVENTS_TOPIC, VERDICTS_TOPIC} & set(others[name]):
            problems.append(f"existing consumer group {name} reads a load-test topic")
    if problems:
        raise IsolationError("; ".join(problems))
    return {"passed": True, "other_active_groups_and_their_topics": others}


async def fire(
    client: httpx.AsyncClient, run: Run, rec: Record, ticker: str, query: str, t0: float
) -> None:
    rec.sent_s = time.monotonic() - t0
    try:
        resp = await client.post("/v1/rag/query", json={"query": query, "ticker": ticker})
        rec.status = resp.status_code
        if resp.headers.get("content-type", "").startswith("application/json"):
            body = resp.json()
            rec.app_trace_id = body.get("retrieval_trace_id") or body.get("app_trace_id")
            rec.block_rail = body.get("rail")
    except Exception as exc:
        rec.error = type(exc).__name__
    rec.done_s = time.monotonic() - t0
    run.responses.append((rec.app_trace_id, rec.status))


async def sequential(client: httpx.AsyncClient, run: Run, n: int) -> list[Record]:
    """n requests one at a time: the unloaded latency of the same path."""
    records = []
    t0 = time.monotonic()
    for _ in range(n):
        seq, ticker, query = run.next_request()
        rec = Record(seq, time.monotonic() - t0)
        await fire(client, run, rec, ticker, query, t0)
        rec.scheduled_s = rec.sent_s or 0.0
        records.append(rec)
    return records


async def run_stage(
    client: httpx.AsyncClient, run: Run, rps: float, duration_s: float
) -> tuple[list[Record], dict[str, Any]]:
    records: list[Record] = []
    tasks: list[asyncio.Task[None]] = []
    in_flight = 0

    def finished(_: object) -> None:
        nonlocal in_flight
        in_flight -= 1

    t0, wall_start = time.monotonic(), time.time()
    for offset in arrival_offsets(rps, duration_s):
        delay = offset - (time.monotonic() - t0)
        if delay > 0:
            await asyncio.sleep(delay)
        if run.abort:
            break
        seq, ticker, query = run.next_request()
        rec = Record(seq, offset)
        records.append(rec)
        if in_flight >= MAX_IN_FLIGHT:
            rec.shed = True
            continue
        in_flight += 1
        task = asyncio.create_task(fire(client, run, rec, ticker, query, t0))
        task.add_done_callback(finished)
        tasks.append(task)
    last_send = time.monotonic() - t0
    await asyncio.gather(*tasks)
    return records, {
        "wall_start": wall_start,
        "wall_end": time.time(),
        "last_send_s": round(last_send, 2),
        "all_done_s": round(time.monotonic() - t0, 2),
    }


async def drain_lag(timeout_s: float) -> dict[str, Any]:
    """Seconds until the flash consumer has no backlog and every event has a verdict."""
    started = time.monotonic()
    peak = 0
    while time.monotonic() - started < timeout_s:
        lag = group_state()["total_lag"] or 0
        peak = max(peak, lag)
        if lag == 0 and high_watermark(VERDICTS_TOPIC) >= high_watermark(EVENTS_TOPIC):
            return {
                "drained": True,
                "seconds": round(time.monotonic() - started, 1),
                "peak_seen": peak,
            }
        await asyncio.sleep(1.0)
    return {"drained": False, "seconds": round(timeout_s, 1), "peak_seen": peak}


async def run_all(run: Run, plan: list[tuple[float, float]], summary: dict[str, Any]) -> None:
    limits = httpx.Limits(max_connections=400)
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=70.0, limits=limits) as client:
        warm = await sequential(client, run, 5)  # loads lazy state; not part of the baseline
        if any(r.status != 200 for r in warm):
            raise RuntimeError(f"warm-up requests failed: {[r.status for r in warm]}")
        baseline = stage_stats(await sequential(client, run, 20), 20.0)
        summary["unloaded_baseline_20_sequential"] = baseline
        run.baseline = read_resources()
        summary["resources_before_load"] = run.baseline
        summary["docker_before_load"] = docker_usage()
        threading.Thread(target=sampler, args=(run,), daemon=True).start()

        stages: list[dict[str, Any]] = []
        summary["stages"] = stages
        for index, (rps, duration) in enumerate(plan):
            run.stage = f"{rps:g}rps"
            breach = resource_breach(read_resources(), run.baseline, LIMITS)
            if breach or run.abort:
                summary["stopped_before"] = {"stage": run.stage, "reason": breach or run.abort}
                break
            if rps >= TARGET_RPS and stages and not stages[-1]["headroom_p99_within_half_budget"]:
                summary["stopped_before"] = {
                    "stage": run.stage,
                    "reason": "the previous stage left no headroom for the 1,000 rpm target",
                }
                break
            records, timing = await run_stage(client, run, rps, duration)
            stats = stage_stats(records, duration)
            violations = slo_violations(stats, SLO)
            stages.append(
                {
                    "offered_rps_target": rps,
                    "offered_rpm_target": round(rps * 60),
                    "duration_s": duration,
                    "stats": stats,
                    "timing": timing,
                    "slo_violations": violations,
                    "slo_met": not violations,
                    "headroom_p99_within_half_budget": has_headroom(stats, SLO),
                    "consumer_drain_after_stage": await drain_lag(60.0),
                    "aborted": run.abort,
                    "docker_after_stage": docker_usage(),
                    "records": [asdict(r) for r in records],
                }
            )
            lines = (json.dumps(r) for s in stages for r in s["records"])
            (run.raw / "records.jsonl").write_text("\n".join(lines))
            if run.abort or violations:
                summary["stopped_after"] = {"stage": run.stage, "reason": run.abort or violations}
                break

        run.stage = "recovery"
        summary["gateway_alive_at_recovery_start"] = bool(run.gateway and run.gateway.alive())
        summary["recovery"] = {"consumer": await drain_lag(120.0)}
        summary["resources_after_load"] = read_resources()
        after = stage_stats(await sequential(client, run, 10), 10.0)
        summary["recovery"]["post_load_10_sequential"] = after
        base_p95 = baseline["latency_ms_all_responses"]["p95"]
        post_p95 = after["latency_ms_all_responses"]["p95"]
        summary["recovery"]["latency_back_to_baseline_p95_within_1_5x"] = bool(
            base_p95 and post_p95 and post_p95 <= base_p95 * 1.5
        )
        run.stop_sampler.set()
        summary["legs"] = await collect_legs(run.responses)


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()


def start_stack(
    args: argparse.Namespace, run: Run, summary: dict[str, Any], procs: list[Proc]
) -> None:
    raw = run.raw
    gw_att, c_att = raw / "gateway.attest.json", raw / "consumer.attest.json"
    stub_args = ["stub", "--port", str(STUB_PORT), "--latency-ms", str(args.stub_latency_ms)]
    procs.append(spawn("stub", stub_args, raw))
    consumer_args = ["consumer", "--topic", EVENTS_TOPIC, "--group", GROUP]
    consumer_args += ["--verdict-topic", VERDICTS_TOPIC, "--attest", str(c_att)]
    procs.append(spawn("consumer", consumer_args, raw))
    consumer_att = wait_for_file(c_att, procs[1], 120)
    gateway_args = ["gateway", "--port", str(GATEWAY_PORT), "--stub-url", STUB_URL]
    gateway_args += [
        "--topic",
        EVENTS_TOPIC,
        "--attest",
        str(gw_att),
        "--spans",
        str(raw / "spans.jsonl"),
    ]
    procs.append(spawn("gateway", gateway_args, raw))
    gateway_att = wait_for_file(gw_att, procs[2], 240)
    run.gateway_pid = gateway_att["pid"]
    run.gateway = procs[2]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = group_state()
        if state["state"] == "Stable" and state["members"]:
            break
        time.sleep(1.0)
    summary["isolation_attestation"] = {"gateway": gateway_att, "consumer": consumer_att}
    summary["isolation_check"] = verify_isolation(gateway_att, consumer_att)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stages", default=DEFAULT_STAGES, help="rps:seconds,rps:seconds,...")
    parser.add_argument("--stub-latency-ms", type=float, default=200.0)
    parser.add_argument("--out", default=str(ROOT / "docs/measurements/load/day10c-load-test.json"))
    args = parser.parse_args()
    plan = [(float(a), float(b)) for a, b in (s.split(":") for s in args.stages.split(","))]

    run_id = secrets.token_hex(3)
    raw = ROOT / "docs/measurements/load/raw" / f"run-{run_id}"
    raw.mkdir(parents=True)
    run = Run(raw)
    summary: dict[str, Any] = {
        "run_id": run_id,
        "started_utc": datetime.now(UTC).isoformat(),
        "git_head": git_head(),
        "command": " ".join(sys.argv),
        "config": {
            "stages_rps_seconds": plan,
            "slo": asdict(SLO),
            "resource_limits": asdict(LIMITS),
            "arrival": "open loop, constant rate",
            "max_in_flight": MAX_IN_FLIGHT,
            "stub_latency_ms": args.stub_latency_ms,
            "query_pool": len(QUESTIONS),
            "kafka_bootstrap": BOOTSTRAP,
        },
    }
    procs: list[Proc] = []
    infra_created = False
    exit_code = 0
    try:
        before = read_resources()
        summary["resources_at_start"] = before
        if before["mem_free_pct"] < 30:
            raise RuntimeError(
                f"free memory {before['mem_free_pct']:g}% is below 30%, not starting"
            )
        create_topics()
        create_tables()
        infra_created = True
        start_stack(args, run, summary, procs)
        asyncio.run(run_all(run, plan, summary))
    except IsolationError as exc:
        summary["isolation_check"] = {"passed": False, "problems": str(exc)}
        summary["outcome"] = "refused: isolation check failed, no load generated"
        exit_code = 2
    except BaseException as exc:
        summary["outcome"] = f"error: {type(exc).__name__}: {exc}"
        exit_code = 1
    finally:
        run.stop_sampler.set()
        for proc in reversed(procs):
            stop(proc)
        finals = {}
        for name in ("gateway", "consumer"):
            final = raw / f"{name}.attest.json.final"
            finals[name] = json.loads(final.read_text()) if final.exists() else "not written"
        summary["tripwire_hits_at_shutdown"] = finals
        if run.gateway is not None:
            summary["gateway_exit_code"] = run.gateway.popen.poll()
            summary["gateway_alive_at_end"] = run.gateway.alive()
        if infra_created:
            summary["teardown"] = teardown_infra()
        try:
            finish_summary(raw, run.samples, summary)
        except Exception as exc:
            summary["finish_error"] = repr(exc)
        summary.setdefault("outcome", "completed")
        summary["finished_utc"] = datetime.now(UTC).isoformat()
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
        print(f"summary written to {args.out}; outcome: {summary['outcome']}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
