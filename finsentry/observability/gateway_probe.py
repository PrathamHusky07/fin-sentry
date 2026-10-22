"""A persisted gateway round-trip probe.

`python -m finsentry.observability.gateway_probe` times a burst of GET requests to the gateway
health route and stores one summary row in gateway_probe_runs. The route runs no retrieval and no
model, so the figure is the cost of reaching the gateway and never a RAG latency. A run writes
nothing to the product evidence (no stream topic, no stream_archive, Red Team or Agent row). The
gateway serves the newest row at /ops/gateway-probe/latest, so the figure is still there, dated,
when nobody has run anything since.

A run that cannot time every request records nothing. A gateway that did not answer produces no
row, never a fast-looking one.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import httpx
import psycopg
from dotenv import load_dotenv
from pydantic import BaseModel

ROUTE = "/health"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_SAMPLES = 30
# Requests sent before timing starts, so the connection setup is not in the figure.
WARMUP_REQUESTS = 2
REQUEST_TIMEOUT_SECONDS = 5.0


class GatewayProbeRun(BaseModel):
    measured_at: datetime
    target: str
    samples: int
    median_ms: float
    p95_ms: float
    max_ms: float


class GatewayProbeSummary(BaseModel):
    """The newest run and how many have been recorded. `latest` is null before the first run."""

    latest: GatewayProbeRun | None
    runs_recorded: int


class ProbeFailedError(Exception):
    """The gateway did not answer every timed request, so no figure was produced."""


def percentile(values: list[float], q: float) -> float:
    """Continuous percentile: linear interpolation at rank q * (n - 1), the same definition as
    PERCENTILE_CONT in the throughput views."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


def time_requests(
    base_url: str, samples: int, transport: httpx.BaseTransport | None = None
) -> list[float]:
    """Round trip of each of `samples` sequential requests over one connection, in milliseconds."""
    url = f"{base_url.rstrip('/')}{ROUTE}"
    durations: list[float] = []
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
            for i in range(WARMUP_REQUESTS + samples):
                start = time.perf_counter()
                response = client.get(url)
                response.read()
                elapsed_ms = (time.perf_counter() - start) * 1000
                response.raise_for_status()
                if i >= WARMUP_REQUESTS:
                    durations.append(elapsed_ms)
    except httpx.HTTPError as exc:
        raise ProbeFailedError(f"{url} did not answer every request: {exc}") from exc
    return durations


def record_run(database_url: str, target: str, durations: list[float]) -> GatewayProbeRun:
    median = percentile(durations, 0.5)
    p95 = percentile(durations, 0.95)
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(
            """
            INSERT INTO gateway_probe_runs
                (target, samples, latencies_ms, median_ms, p95_ms, max_ms)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING measured_at
            """,
            (target, len(durations), durations, median, p95, max(durations)),
        ).fetchone()
    assert row is not None
    return GatewayProbeRun(
        measured_at=row[0],
        target=target,
        samples=len(durations),
        median_ms=median,
        p95_ms=p95,
        max_ms=max(durations),
    )


def latest_summary(database_url: str) -> GatewayProbeSummary:
    with psycopg.connect(database_url, autocommit=True) as conn:
        count_row = conn.execute("SELECT count(*) FROM gateway_probe_runs").fetchone()
        row = conn.execute(
            """
            SELECT measured_at, target, samples, median_ms, p95_ms, max_ms
            FROM gateway_probe_runs
            ORDER BY measured_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    runs = int(count_row[0]) if count_row else 0
    latest = (
        GatewayProbeRun(
            measured_at=row[0],
            target=row[1],
            samples=row[2],
            median_ms=row[3],
            p95_ms=row[4],
            max_ms=row[5],
        )
        if row
        else None
    )
    return GatewayProbeSummary(latest=latest, runs_recorded=runs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")

    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set, so the run cannot be stored.", file=sys.stderr)
        return 2
    try:
        durations = time_requests(args.base_url, args.samples)
    except ProbeFailedError as exc:
        print(f"Nothing recorded. {exc}", file=sys.stderr)
        return 1
    run = record_run(database_url, f"{args.base_url.rstrip('/')}{ROUTE}", durations)
    print(
        f"Recorded {run.samples} requests to {run.target} at {run.measured_at.isoformat()}: "
        f"median {run.median_ms:.1f} ms, p95 {run.p95_ms:.1f} ms, max {run.max_ms:.1f} ms."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
