"""The gateway's /ops/metrics/throughput/history proxy: the same Option C
boundary as the trace routes. It makes an httpx call to the dashboard and
never touches RisingWave."""

from __future__ import annotations

import datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.events.metrics_snapshot import ThroughputBucket, ThroughputHistory
from finsentry.gateway.main import app

_START = datetime.datetime(2026, 10, 6, 2, 25, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    gw._metrics_http_client = None


def _history() -> ThroughputHistory:
    return ThroughputHistory(
        generated_at=_START + datetime.timedelta(hours=1),
        risingwave_connected=True,
        limit=60,
        window_start=_START,
        window_end=_START + datetime.timedelta(minutes=1),
        buckets=[
            ThroughputBucket(
                window_start=_START,
                window_end=_START + datetime.timedelta(minutes=1),
                total_requests=3,
                success_count=3,
                blocked_count=0,
                error_count=0,
                avg_latency_ms=100.0,
                p95_latency_ms=100.5,
            )
        ],
    )


async def test_returns_503_when_the_client_is_not_initialised() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/metrics/throughput/history")
    assert resp.status_code == 503


async def test_proxies_the_dashboard_response_and_forwards_limit() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["limit"] = request.url.params["limit"]
        return httpx.Response(200, content=_history().model_dump_json())

    gw._metrics_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/metrics/throughput/history", params={"limit": 12})

    assert resp.status_code == 200
    assert seen == {"path": "/metrics/throughput/history", "limit": "12"}
    body = resp.json()
    assert body["buckets"][0]["total_requests"] == 3
    assert body["risingwave_connected"] is True


async def test_returns_503_when_the_dashboard_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    gw._metrics_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/metrics/throughput/history")

    assert resp.status_code == 503


async def test_limit_is_range_checked() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/metrics/throughput/history", params={"limit": 0})
    assert resp.status_code == 422
