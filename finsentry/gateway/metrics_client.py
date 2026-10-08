"""
Internal HTTP client the gateway uses to fetch a MetricsSnapshot from the
dashboard/metrics process (Day 8, Option C): RisingWave access stays
entirely in that process -- the gateway never imports RisingWavePool or
psycopg_pool. Read METRICS_SERVICE_URL from here; do not hardcode the URL
elsewhere in gateway code.

METRICS_SERVICE_URL is the dashboard's base URL: defaults to
http://localhost:8081 (the dashboard's own documented local-dev port, see
finsentry/dashboard/app.py) for local dev, set to http://dashboard:8081 in
the Day 8 Docker Compose network.
"""

from __future__ import annotations

import os

import httpx

from finsentry.events.metrics_snapshot import MetricsSnapshot, ThroughputHistory
from finsentry.events.trace_api import (
    CalibrationHealthResponse,
    TraceDetailResponse,
    TraceListResponse,
)

METRICS_SERVICE_URL: str = os.getenv("METRICS_SERVICE_URL", "http://localhost:8081")


async def fetch_snapshot(client: httpx.AsyncClient, timeout: float = 5.0) -> MetricsSnapshot:
    """Fetch one MetricsSnapshot from the metrics service.

    Raises httpx.HTTPError (or a subclass) on any failure -- unreachable
    service, non-2xx response, or connection timeout. Raises
    pydantic.ValidationError if the response doesn't match the contract.
    This function never fabricates a snapshot; the caller (the Day 8 SSE
    poller) decides what to do when a fetch fails.
    """
    resp = await client.get(f"{METRICS_SERVICE_URL}/metrics/snapshot", timeout=timeout)
    resp.raise_for_status()
    return MetricsSnapshot.model_validate(resp.json())


async def fetch_trace_list(
    client: httpx.AsyncClient,
    limit: int,
    offset: int,
    ticker: str | None,
    status: str | None,
    q: str | None = None,
    judge_state: str | None = None,
    frontier_sampled: bool | None = None,
    disagreement: bool | None = None,
    timeout: float = 5.0,
) -> TraceListResponse:
    """Fetch the Investigations trace list from the dashboard's /traces
    route. Raises httpx.HTTPError on any failure; the caller's route handler
    decides what to return to the browser."""
    params: dict[str, str | int | bool] = {"limit": limit, "offset": offset}
    if ticker is not None:
        params["ticker"] = ticker
    if status is not None:
        params["status"] = status
    if q is not None:
        params["q"] = q
    if judge_state is not None:
        params["judge_state"] = judge_state
    if frontier_sampled is not None:
        params["frontier_sampled"] = frontier_sampled
    if disagreement is not None:
        params["disagreement"] = disagreement
    resp = await client.get(f"{METRICS_SERVICE_URL}/traces", params=params, timeout=timeout)
    resp.raise_for_status()
    return TraceListResponse.model_validate(resp.json())


async def fetch_trace_detail(
    client: httpx.AsyncClient, app_trace_id: str, timeout: float = 5.0
) -> TraceDetailResponse:
    """Fetch one trace's drill-down detail from the dashboard's
    /traces/{app_trace_id} route. Raises httpx.HTTPError on any failure."""
    resp = await client.get(f"{METRICS_SERVICE_URL}/traces/{app_trace_id}", timeout=timeout)
    resp.raise_for_status()
    return TraceDetailResponse.model_validate(resp.json())


async def fetch_calibration_health(
    client: httpx.AsyncClient, timeout: float = 5.0
) -> CalibrationHealthResponse:
    """Fetch the calibration-health panel from the dashboard's
    /calibration/health route. Raises httpx.HTTPError on any failure."""
    resp = await client.get(f"{METRICS_SERVICE_URL}/calibration/health", timeout=timeout)
    resp.raise_for_status()
    return CalibrationHealthResponse.model_validate(resp.json())


async def fetch_throughput_history(
    client: httpx.AsyncClient, limit: int, timeout: float = 5.0
) -> ThroughputHistory:
    """Fetch the latest persisted throughput buckets from the dashboard's
    /metrics/throughput/history route. Raises httpx.HTTPError on any failure."""
    resp = await client.get(
        f"{METRICS_SERVICE_URL}/metrics/throughput/history",
        params={"limit": limit},
        timeout=timeout,
    )
    resp.raise_for_status()
    return ThroughputHistory.model_validate(resp.json())
