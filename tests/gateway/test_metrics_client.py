"""Tests for finsentry.gateway.metrics_client -- the gateway's internal
httpx client for fetching a MetricsSnapshot from the dashboard, with zero
RisingWave coupling in the gateway itself."""

from __future__ import annotations

import datetime

import httpx
import pytest
from pydantic import ValidationError

from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.gateway.metrics_client import METRICS_SERVICE_URL, fetch_snapshot

_SNAPSHOT_JSON = MetricsSnapshot(
    generated_at=datetime.datetime.now(datetime.UTC),
    risingwave_connected=True,
    frontier=None,
).model_dump_json()


async def test_fetch_snapshot_parses_real_contract_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/metrics/snapshot"
        return httpx.Response(200, content=_SNAPSHOT_JSON)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        snapshot = await fetch_snapshot(client)

    assert isinstance(snapshot, MetricsSnapshot)
    assert snapshot.risingwave_connected is True
    assert snapshot.throughput is None


async def test_fetch_snapshot_raises_on_non_2xx() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, content=b"unavailable"))
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_snapshot(client)


async def test_fetch_snapshot_raises_on_malformed_contract() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"garbage": True}))
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        with pytest.raises(ValidationError):
            await fetch_snapshot(client)


async def test_fetch_snapshot_raises_on_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        with pytest.raises(httpx.ConnectError):
            await fetch_snapshot(client)
