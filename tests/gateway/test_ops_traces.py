"""Tests for the gateway's /ops/traces, /ops/traces/{id}, and
/ops/calibration/health routes -- the Day 9 proxy routes that keep the
gateway the single browser-facing origin by making an httpx call to the
dashboard's internal endpoints, exactly like the Day 8 metrics poller does.
No RisingWave import, no cross-process function call."""

from __future__ import annotations

import datetime

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.events.trace_api import (
    CalibrationHealthResponse,
    FrontierSectionView,
    TraceDetailResponse,
    TraceListResponse,
)
from finsentry.gateway.main import app


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    gw._metrics_http_client = None


async def test_ops_traces_returns_503_when_client_not_initialised() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/traces")
    assert resp.status_code == 503


async def test_ops_traces_proxies_dashboard_response() -> None:
    body = TraceListResponse(traces=[], next_offset=None, risingwave_connected=True)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body.model_dump_json())
    )
    gw._metrics_http_client = httpx.AsyncClient(transport=transport)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/traces", params={"limit": 10})

    assert resp.status_code == 200
    assert resp.json()["risingwave_connected"] is True


async def test_ops_traces_returns_503_when_dashboard_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    gw._metrics_http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/traces")

    assert resp.status_code == 503


async def test_ops_trace_detail_proxies_dashboard_response() -> None:
    body = TraceDetailResponse(
        app_trace_id="abc-123",
        found=True,
        rag_status="success",
        endpoint="rag",
        ticker="AAPL",
        query="q",
        answer="a",
        confidence="high",
        model_used="llama3.1:8b",
        citations=[],
        retrieved_chunk_ids=[],
        block_reason=None,
        block_rail=None,
        error_kind=None,
        error_detail=None,
        timestamp_utc=datetime.datetime.now(datetime.UTC),
        judge_state="evaluated",
        flash=None,
        frontier=FrontierSectionView(sampled=False, evidence=None, note="not sampled"),
        risingwave_connected=True,
        note="persisted trace snapshot",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body.model_dump_json())
    )
    gw._metrics_http_client = httpx.AsyncClient(transport=transport)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/traces/abc-123")

    assert resp.status_code == 200
    assert resp.json()["app_trace_id"] == "abc-123"


async def test_ops_calibration_health_proxies_dashboard_response() -> None:
    body = CalibrationHealthResponse(
        judge_id="gemini-rubric",
        kappa=0.5161290322580646,
        state="degraded",
        window_n=30,
        min_n=30,
        healthy_baseline_kappa=0.605,
        drift_entry_threshold=0.43,
        recovery_threshold=0.54,
        position="between_thresholds",
        state_as_of="2026-10-04T17:11:36.780302+00:00",
        note="reporting last-persisted state as of state_as_of",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body.model_dump_json())
    )
    gw._metrics_http_client = httpx.AsyncClient(transport=transport)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/calibration/health")

    assert resp.status_code == 200
    assert resp.json()["position"] == "between_thresholds"
