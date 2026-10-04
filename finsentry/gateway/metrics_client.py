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

from finsentry.events.metrics_snapshot import MetricsSnapshot

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
