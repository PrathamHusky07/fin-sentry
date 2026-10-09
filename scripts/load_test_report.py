"""Analysis for scripts/load_test.py: per-stage span latency, leg-by-leg reconciliation and
the final summary shape. Reads the load-test topics and RisingWave tables directly."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from load_test_io import (
    EVENTS_TABLE,
    EVENTS_TOPIC,
    VERDICTS_TABLE,
    VERDICTS_TOPIC,
    read_topic,
    risingwave_rows,
)
from load_test_lib import percentile, reconcile


def span_stats(spans_path: Path, start: float, end: float) -> dict[str, Any]:
    by_name: dict[str, list[float]] = defaultdict(list)
    for line in spans_path.read_text().splitlines():
        row = json.loads(line)
        if start <= row["t"] <= end:
            by_name[row["n"]].append(row["ms"])
    return {
        name: {
            "count": len(v),
            "p50_ms": percentile(v, 50),
            "p95_ms": percentile(v, 95),
            "mean_ms": round(sum(v) / len(v), 1),
        }
        for name, v in sorted(by_name.items())
    }


async def collect_legs(responses: list[tuple[str | None, int | None]]) -> dict[str, Any]:
    """Read every leg after the run: the event topic, the verdict topic, then the
    RisingWave tables once they have caught up with both topics."""
    events = await read_topic(EVENTS_TOPIC)
    verdicts = await read_topic(VERDICTS_TOPIC)
    event_ids = Counter(e["app_trace_id"] for e in events)
    verdict_ids = [v["app_trace_id"] for v in verdicts]
    server_ms = {e["app_trace_id"]: e["total_latency_ms"] for e in events}
    event_status = Counter(e["status"] for e in events)
    faithfulness = [e.get("output_rail_trace_snapshot", {}).get("faithfulness", {}) for e in events]
    started = time.monotonic()
    while time.monotonic() - started < 60:
        have_events = risingwave_rows(f"SELECT count(*) FROM {EVENTS_TABLE}")[0][0]
        have_verdicts = risingwave_rows(f"SELECT count(*) FROM {VERDICTS_TABLE}")[0][0]
        if have_events >= len(events) and have_verdicts >= len(verdicts):
            break
        await asyncio.sleep(2.0)
    persisted_events = Counter(
        r[0] for r in risingwave_rows(f"SELECT app_trace_id FROM {EVENTS_TABLE}")
    )
    persisted_verdicts = [
        r[0] for r in risingwave_rows(f"SELECT app_trace_id FROM {VERDICTS_TABLE}")
    ]
    return {
        "reconciliation": reconcile(
            responses, event_ids, verdict_ids, persisted_events, persisted_verdicts
        ),
        "event_status_counts": dict(event_status),
        "persistence_wait_s": round(time.monotonic() - started, 1),
        "server_latency_ms_by_trace_id": server_ms,
        "model_calls_seen": {
            "faithfulness_gemini_calls_in_events": sum(
                int(f.get("gemini_calls", 0) or 0) for f in faithfulness
            ),
            "judge_total_gemini_calls_in_verdicts": sum(
                int(v.get("total_gemini_calls", 0) or 0) for v in verdicts
            ),
            "faithfulness_status_in_events": dict(
                Counter(
                    str(f.get("faithfulness_status", f.get("status"))) for f in faithfulness if f
                )
            ),
            "judge_faithfulness_status_in_verdicts": dict(
                Counter(str(v.get("faithfulness_status")) for v in verdicts)
            ),
        },
    }


def _peak(samples: list[dict[str, Any]], key: str, fn: Any) -> Any:
    values = [s[key] for s in samples if s.get(key) is not None]
    return fn(values) if values else None


def finish_summary(raw: Path, samples: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    """Fold the per-request records and samples into each stage's summary entry."""
    legs = summary.get("legs", {})
    server_ms = legs.pop("server_latency_ms_by_trace_id", {})
    spans = raw / "spans.jsonl"
    for stage in summary.get("stages", []):
        records = stage.pop("records")
        ms = [server_ms[r["app_trace_id"]] for r in records if r["app_trace_id"] in server_ms]
        stage["server_latency_ms_from_events"] = {
            "events_matched_by_trace_id": len(ms),
            "p50": percentile(ms, 50),
            "p95": percentile(ms, 95),
            "p99": percentile(ms, 99),
        }
        window = stage["timing"]
        if spans.exists():
            stage["span_latency"] = span_stats(spans, window["wall_start"], window["wall_end"] + 1)
        label = f"{stage['offered_rps_target']:g}rps"
        in_stage = [s for s in samples if s.get("stage") == label]
        stage["sampled"] = {
            "samples": len(in_stage),
            "peak_consumer_lag": _peak(in_stage, "consumer_lag", max),
            "min_mem_free_pct": _peak(in_stage, "mem_free_pct", min),
            "max_swap_used_mb": _peak(in_stage, "swap_used_mb", max),
            "max_load_1m": _peak(in_stage, "load_1m", max),
            "max_gateway_cpu_pct": _peak(in_stage, "gateway_cpu_pct", max),
            "max_gateway_rss_mb": _peak(in_stage, "gateway_rss_mb", max),
        }
    (raw / "samples.json").write_text(json.dumps(samples, indent=1))
