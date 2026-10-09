"""Pure helpers for the Day 10C load test.

Everything here is deterministic and unit-tested in tests/scripts/test_load_test_lib.py:
the arrival schedule, the correlation token, percentiles and the stage verdict, the
isolation attestation checks that fail closed, the egress tripwire, and the
reconciliation of request, event, verdict and persisted-row counts.
"""

from __future__ import annotations

import math
import os
import re
import socket
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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


# --- reconciliation ---------------------------------------------------------


def reconcile(
    responses: Sequence[tuple[str | None, int | None]],
    event_ids: Mapping[str, int],
    verdict_ids: Iterable[str],
    persisted_event_ids: Mapping[str, int],
    persisted_verdict_ids: Iterable[str],
) -> dict[str, Any]:
    """Count what each leg saw and name the gaps between adjacent legs.

    `responses` is one (app_trace_id, HTTP status) pair per request sent. The gateway
    returns the trace id only on a 200 or a 504, so a blocked request, a 5xx or a timeout
    cannot be matched to its event by id. Those are reconciled by count instead:
    `unmatched_events_minus_requests_without_id` is zero when every event without a
    matching response id is explained by a request that returned no id."""
    response_ids = {i for i, _ in responses if i is not None}
    events = set(event_ids)
    verdicts = set(verdict_ids)
    persisted = set(persisted_event_ids)
    persisted_verdicts = set(persisted_verdict_ids)
    requests_without_id = len(responses) - len(response_ids)
    unmatched = len(events - response_ids)
    return {
        "sent_requests": len(responses),
        "http_responses": sum(1 for _, s in responses if s is not None),
        "responses_with_trace_id": len(response_ids),
        "requests_without_trace_id": requests_without_id,
        "events_in_topic_total": sum(event_ids.values()),
        "events_in_topic_unique": len(events),
        "duplicate_events": sum(n - 1 for n in event_ids.values() if n > 1),
        "response_id_without_event": len(response_ids - events),
        "response_id_without_event_examples": sorted(response_ids - events)[:5],
        "events_unmatched_to_a_response_id": unmatched,
        "unmatched_events_minus_requests_without_id": unmatched - requests_without_id,
        "verdicts_unique": len(verdicts),
        "event_without_verdict": len(events - verdicts),
        "verdict_without_event": len(verdicts - events),
        "persisted_events_unique": len(persisted),
        "topic_event_not_persisted": len(events - persisted),
        "persisted_verdicts_unique": len(persisted_verdicts),
        "verdict_not_persisted": len(verdicts - persisted_verdicts),
    }
