"""Pure helpers for the Day 10C load test.

Everything here is deterministic and unit-tested in tests/scripts/test_load_test_lib.py:
the arrival schedule, the correlation token, percentiles and the stage verdict, the
isolation attestation checks that fail closed, the egress tripwire, and the
reconciliation of request, event, verdict and persisted-row counts.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import socket
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

# --- arrival schedule and statistics ----------------------------------------


def arrival_offsets(rps: float, duration_s: float) -> list[float]:
    """Open-loop constant-rate arrivals: request i is due at i / rps seconds."""
    return [i / rps for i in range(round(rps * duration_s))]


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, q in (0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


@dataclass
class Record:
    """One offered request. Times are seconds from the start of its stage."""

    seq: int
    scheduled_s: float
    sent_s: float | None = None
    done_s: float | None = None
    status: int | None = None
    error: str | None = None
    app_trace_id: str | None = None
    block_rail: str | None = None
    shed: bool = False


@dataclass(frozen=True)
class Slo:
    p95_ms: float = 3000.0
    p99_ms: float = 5000.0
    max_error_rate: float = 0.01


def stage_stats(records: Sequence[Record], duration_s: float) -> dict[str, Any]:
    """Offered load, achieved throughput and latency, kept as separate numbers.

    Latency is measured from the scheduled arrival time, so a request that waited behind
    a stalled client still counts the wait (no coordinated omission). A request with no
    HTTP response is an error and has no latency."""
    offered = len(records)
    responded = [r for r in records if r.status is not None and r.done_s is not None]
    ok = [r for r in responded if r.status == 200]
    lat = [(r.done_s - r.scheduled_s) * 1000 for r in responded if r.done_s is not None]
    lat_ok = [(r.done_s - r.scheduled_s) * 1000 for r in ok if r.done_s is not None]
    sent = [r for r in records if r.sent_s is not None]
    span = None
    if ok and sent:
        span = max(r.done_s for r in ok if r.done_s is not None) - min(
            r.sent_s for r in sent if r.sent_s is not None
        )
    return {
        "offered_requests": offered,
        "offered_rps": round(offered / duration_s, 3),
        "sent": len(sent),
        "shed_by_client": sum(r.shed for r in records),
        "http_responses": len(responded),
        "no_response": len(sent) - len(responded),
        "status_counts": dict(Counter(str(r.status) for r in responded)),
        "blocked_by_rail": dict(Counter(r.block_rail for r in responded if r.block_rail)),
        "ok_200": len(ok),
        "error_rate": round((offered - len(ok)) / offered, 4) if offered else 0.0,
        "achieved_rps_busy_span": round(len(ok) / span, 3) if span else None,
        "achieved_rps_in_window": round(
            sum(1 for r in ok if r.done_s is not None and r.done_s <= duration_s) / duration_s, 3
        ),
        "latency_ms_all_responses": _latency(lat),
        "latency_ms_200_only": _latency(lat_ok),
    }


def _latency(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "p50": _r(percentile(values, 50)),
        "p95": _r(percentile(values, 95)),
        "p99": _r(percentile(values, 99)),
        "max": _r(max(values) if values else None),
    }


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def slo_violations(stats: Mapping[str, Any], slo: Slo) -> list[str]:
    problems: list[str] = []
    lat = stats["latency_ms_all_responses"]
    if lat["p95"] is None:
        problems.append("no HTTP response was received")
        return problems
    if lat["p95"] > slo.p95_ms:
        problems.append(f"p95 {lat['p95']} ms exceeds {slo.p95_ms:g} ms")
    if lat["p99"] > slo.p99_ms:
        problems.append(f"p99 {lat['p99']} ms exceeds {slo.p99_ms:g} ms")
    if stats["error_rate"] > slo.max_error_rate:
        problems.append(f"error rate {stats['error_rate']} exceeds {slo.max_error_rate}")
    return problems


def has_headroom(stats: Mapping[str, Any], slo: Slo, fraction: float = 0.5) -> bool:
    """True when the stage met the SLO with p99 at or under `fraction` of its budget."""
    p99 = stats["latency_ms_all_responses"]["p99"]
    return not slo_violations(stats, slo) and p99 is not None and p99 <= slo.p99_ms * fraction


# --- resources --------------------------------------------------------------


def parse_resources(memory_pressure_out: str, swap_out: str) -> dict[str, float]:
    free = re.search(r"free percentage:\s*(\d+)%", memory_pressure_out)
    used = re.search(r"used = ([\d.]+)M", swap_out)
    swap_free = re.search(r"free = ([\d.]+)M", swap_out)
    if not (free and used and swap_free):
        raise ValueError("could not parse the memory readings")
    return {
        "mem_free_pct": float(free.group(1)),
        "swap_used_mb": float(used.group(1)),
        "swap_free_mb": float(swap_free.group(1)),
        "load_1m": os.getloadavg()[0],
    }


def read_resources() -> dict[str, float]:
    mp = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=15).stdout
    swap = subprocess.run(
        ["sysctl", "vm.swapusage"], capture_output=True, text=True, timeout=5
    ).stdout
    return parse_resources(mp, swap)


@dataclass(frozen=True)
class ResourceLimits:
    # Swap is not bounded on macOS (the OS adds swap files on demand), so only its growth
    # past the reading taken just before load is limited, not its remaining headroom.
    min_mem_free_pct: float = 20.0
    max_swap_growth_mb: float = 1500.0


def resource_breach(
    now: Mapping[str, float], baseline: Mapping[str, float], limits: ResourceLimits
) -> str | None:
    if now["mem_free_pct"] < limits.min_mem_free_pct:
        return f"free memory {now['mem_free_pct']:g}% is below {limits.min_mem_free_pct:g}%"
    growth = now["swap_used_mb"] - baseline["swap_used_mb"]
    if growth > limits.max_swap_growth_mb:
        return f"swap grew {growth:.0f} MB, over {limits.max_swap_growth_mb:g} MB"
    return None


def check_resources(
    read: Callable[[], dict[str, float]], baseline: Mapping[str, float], limits: ResourceLimits
) -> tuple[dict[str, float] | None, str | None]:
    """One monitored reading and the reason to abort, if any. A reading that cannot be
    taken is an abort reason, because load must not continue unmonitored."""
    try:
        reading = read()
    except Exception as exc:
        return None, f"resource monitoring failed: {exc!r}"
    breach = resource_breach(reading, baseline, limits)
    return reading, f"resource limit: {breach}" if breach else None


# --- egress tripwire --------------------------------------------------------

_BLOCKED_SUFFIXES = ("googleapis.com", "google.internal", "aiplatform.googleapis.com")
GEMINI_ENV_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
)


def is_blocked_host(host: str) -> bool:
    name = host.lower().rstrip(".")
    return any(name == s or name.endswith("." + s) for s in _BLOCKED_SUFFIXES)


class EgressTripwire:
    """Turns any attempt to resolve a Google API host into an error and a count.

    This is the second line behind GEMINI_MODE=disabled: if any code path in the process
    still tried to reach Gemini, it would fail loudly and the hit would be recorded."""

    def __init__(self) -> None:
        self.hits: list[str] = []
        self.installed = False
        self._real: Callable[..., Any] = socket.getaddrinfo

    def install(self) -> None:
        real = self._real

        def guarded(host: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(host, str) and is_blocked_host(host):
                self.hits.append(host)
                raise OSError(f"egress blocked by the load-test tripwire: {host}")
            return real(host, *args, **kwargs)

        socket.getaddrinfo = guarded  # type: ignore[assignment]
        self.installed = True

    def uninstall(self) -> None:
        socket.getaddrinfo = self._real  # type: ignore[assignment]
        self.installed = False


# --- isolation attestation (fail closed) ------------------------------------


def gateway_attestation_problems(att: Mapping[str, Any], expect: Mapping[str, str]) -> list[str]:
    """Everything that must hold before load may be generated through the gateway."""
    checks: list[tuple[bool, str]] = [
        (att.get("faithfulness_mode") == "disabled", "faithfulness rail is not disabled"),
        (att.get("faithfulness_enabled") is False, "faithfulness rail reports enabled"),
        (att.get("faithfulness_client_present") is False, "faithfulness rail holds a model client"),
        (att.get("gemini_env_present") == [], "Gemini credentials are present in the environment"),
        (att.get("downstream_url") == expect["stub_url"], "downstream is not the local stub"),
        (att.get("producer_mode") == "kafka", "event producer is not in kafka mode"),
        (att.get("producer_topic") == expect["topic"], "event producer targets another topic"),
        (att.get("tripwire_installed") is True, "egress tripwire is not installed"),
        (att.get("tripwire_hits") == [], "egress tripwire already fired"),
        (att.get("hf_offline") is True, "model hub access is not offline"),
    ]
    return [message for ok, message in checks if not ok]


def consumer_attestation_problems(att: Mapping[str, Any], expect: Mapping[str, str]) -> list[str]:
    checks: list[tuple[bool, str]] = [
        (att.get("judge_mode") == "disabled", "flash judge is not disabled"),
        (att.get("judge_client_present") is False, "flash judge holds a model client"),
        (att.get("gemini_env_present") == [], "Gemini credentials are present in the environment"),
        (att.get("topic") == expect["topic"], "consumer reads another topic"),
        (att.get("group") == expect["group"], "consumer uses another group"),
        (att.get("verdict_topic") == expect["verdict_topic"], "consumer writes another topic"),
        (att.get("tripwire_installed") is True, "egress tripwire is not installed"),
        (att.get("tripwire_hits") == [], "egress tripwire already fired"),
    ]
    return [message for ok, message in checks if not ok]


def parse_group_describe(text: str) -> dict[str, Any]:
    """State, member count, total lag and assigned topics from `rpk group describe`."""
    fields: dict[str, str] = {}
    topics: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isupper():
            fields[parts[0]] = parts[1]
        elif len(parts) >= 3 and parts[1].isdigit() and not parts[0].isupper():
            topics.add(parts[0])
    lag = fields.get("TOTAL-LAG", "")
    return {
        "state": fields.get("STATE"),
        "members": int(fields.get("MEMBERS", "0")),
        "total_lag": int(lag) if lag.isdigit() else None,
        "topics": sorted(topics),
    }


# --- backlog drain ----------------------------------------------------------

DrainState = Literal["drained", "backlog", "unknown"]


def drain_state(lag: int | None, verdict_mark: int | None, event_mark: int | None) -> DrainState:
    """Drained needs a readable zero lag and a verdict for every event. A reading that
    could not be taken is unknown, never zero."""
    if lag is None or verdict_mark is None or event_mark is None:
        return "unknown"
    return "drained" if lag == 0 and verdict_mark >= event_mark else "backlog"


async def wait_for_drain(
    read: Callable[[], tuple[int | None, int | None, int | None]],
    timeout_s: float,
    poll_s: float = 1.0,
) -> dict[str, Any]:
    """Poll `read` (lag, verdict topic mark, event topic mark) until the backlog is drained.

    `drained` is True or False only when the last reading was readable. If the last
    reading could not be taken, the answer is None and the status is unknown."""
    started = time.monotonic()
    peak: int | None = None
    unreadable = 0
    while True:
        lag, verdict_mark, event_mark = read()
        state = drain_state(lag, verdict_mark, event_mark)
        unreadable += state == "unknown"
        if lag is not None:
            peak = lag if peak is None else max(peak, lag)
        elapsed = time.monotonic() - started
        if state == "drained":
            return _drain_result("drained", elapsed, peak, unreadable)
        if elapsed >= timeout_s:
            status = "unknown" if state == "unknown" else "not_drained"
            return _drain_result(status, timeout_s, peak, unreadable)
        await asyncio.sleep(poll_s)


def _drain_result(status: str, seconds: float, peak: int | None, unreadable: int) -> dict[str, Any]:
    return {
        "status": status,
        "drained": {"drained": True, "not_drained": False}.get(status),
        "seconds": round(seconds, 1),
        "peak_seen": peak,
        "unreadable_polls": unreadable,
    }


# --- reconciliation ---------------------------------------------------------


Status = Literal["pass", "fail", "unknown"]


def _table(ids: Mapping[str, int]) -> dict[str, Any]:
    duplicated = sorted(i for i, n in ids.items() if n > 1)
    return {
        "rows": sum(ids.values()),
        "unique_ids": len(ids),
        "duplicate_rows": sum(n - 1 for n in ids.values() if n > 1),
        "duplicate_id_examples": duplicated[:5],
    }


def _by_id_population(
    ids: set[str], legs: tuple[set[str], set[str], set[str], set[str]], empty: Status
) -> dict[str, Any]:
    """Reconcile responses that carry a trace id across all four legs: event topic,
    verdict topic, persisted events and persisted verdicts. Every one of them must be on
    every leg, so a missing leg fails the population and is named by id."""
    events, verdicts, persisted, persisted_verdicts = legs
    status: Status = empty
    if ids:
        status = "pass" if all(ids <= leg for leg in legs) else "fail"
    return {
        "count": len(ids),
        "with_event": len(ids & events),
        "with_verdict": len(ids & verdicts),
        "with_persisted_event": len(ids & persisted),
        "with_persisted_verdict": len(ids & persisted_verdicts),
        "missing_event_examples": sorted(ids - events)[:5],
        "missing_persisted_verdict_examples": sorted(ids - persisted_verdicts)[:5],
        "status": status,
    }


def reconcile(
    responses: Sequence[tuple[str | None, int | None]],
    event_ids: Mapping[str, int],
    verdict_ids: Mapping[str, int],
    persisted_event_ids: Mapping[str, int],
    persisted_verdict_ids: Mapping[str, int],
) -> dict[str, Any]:
    """Reconcile what each leg saw, with an explicit status per population.

    `responses` is one (app_trace_id, HTTP status) pair per request sent. Each leg is a
    Counter of ids, so a duplicated row stays visible. The gateway returns the trace id
    only on a 200 or a 504, so a blocked request, a 5xx or a timeout cannot be matched to
    its event by id. Four populations are therefore kept apart:

    1. successful responses with a trace id: each must have an event, a verdict and a
       persisted row of each kind. This is the claim that is proven by id.
    1b. other responses with a trace id (the 504): the gateway emits an error event for
       them and the flash judge writes a skipped verdict for every non-success event, so
       each is owed the same four legs and is reconciled the same way, apart from the 200s.
    2. HTTP responses without a trace id, and 3. requests with no HTTP response: neither
       can be matched by id, and neither is assumed to have produced an event. They are
       compared against the events that match no response id. No unmatched event is a pass.
       An unmatched event leaves them unknown, because the source cannot be told apart.
       More unmatched events than requests without an id could explain is a fail, reported
       under `unmatched_events`.
    """
    ok_ids = {i for i, s in responses if i is not None and s == 200}
    other_ids = {i for i, s in responses if i is not None and s != 200}
    answered_no_id = [s for i, s in responses if i is None and s is not None]
    no_response = sum(1 for i, s in responses if i is None and s is None)
    events, verdicts = set(event_ids), set(verdict_ids)
    persisted, persisted_verdicts = set(persisted_event_ids), set(persisted_verdict_ids)

    unmatched = events - ok_ids - other_ids
    explainable = len(answered_no_id) + no_response

    def id_less_status(count: int) -> Status:
        return "pass" if count == 0 or not unmatched else "unknown"

    legs = (events, verdicts, persisted, persisted_verdicts)
    tables = {
        "events_topic": _table(event_ids),
        "verdicts_topic": _table(verdict_ids),
        "events_persisted": _table(persisted_event_ids),
        "verdicts_persisted": _table(persisted_verdict_ids),
    }
    with_duplicates = [name for name, t in tables.items() if t["duplicate_rows"]]
    row_counts = {
        "events_topic": tables["events_topic"]["rows"],
        "events_persisted": tables["events_persisted"]["rows"],
        "verdicts_topic": tables["verdicts_topic"]["rows"],
        "verdicts_persisted": tables["verdicts_persisted"]["rows"],
    }
    counts_agree = (
        row_counts["events_topic"] == row_counts["events_persisted"]
        and row_counts["verdicts_topic"] == row_counts["verdicts_persisted"]
    )
    return {
        "sent_requests": len(responses),
        "http_responses": sum(1 for _, s in responses if s is not None),
        "populations": {
            "successful_with_trace_id": _by_id_population(ok_ids, legs, "unknown"),
            "http_response_without_trace_id": {
                "count": len(answered_no_id),
                "status_counts": dict(Counter(str(s) for s in answered_no_id)),
                "status": id_less_status(len(answered_no_id)),
            },
            "no_http_response": {"count": no_response, "status": id_less_status(no_response)},
            "other_responses_with_trace_id": _by_id_population(other_ids, legs, "pass"),
        },
        "unmatched_events": {
            "count": len(unmatched),
            "examples": sorted(unmatched)[:5],
            "attributable_requests_without_id": explainable,
            "status": "pass" if len(unmatched) <= explainable else "fail",
        },
        "duplicates": {
            "status": "fail" if with_duplicates else "pass",
            "tables_with_duplicates": with_duplicates,
        },
        "tables": tables,
        "row_counts": {**row_counts, "status": "pass" if counts_agree else "fail"},
        "event_without_verdict": len(events - verdicts),
        "verdict_without_event": len(verdicts - events),
        "topic_event_not_persisted": len(events - persisted),
        "verdict_not_persisted": len(verdicts - persisted_verdicts),
    }
