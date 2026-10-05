"""Tests for finsentry.gateway.metrics_client -- the gateway's internal
httpx client for fetching a MetricsSnapshot from the dashboard, with zero
RisingWave coupling in the gateway itself."""

from __future__ import annotations

import datetime

import httpx
import pytest
from pydantic import ValidationError

from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.events.trace_api import (
    CalibrationHealthResponse,
    FrontierSectionView,
    TraceDetailResponse,
    TraceListResponse,
)
from finsentry.gateway.metrics_client import (
    METRICS_SERVICE_URL,
    fetch_calibration_health,
    fetch_snapshot,
    fetch_trace_detail,
    fetch_trace_list,
)

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


async def test_fetch_trace_list_forwards_query_params_and_parses_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/traces"
        assert dict(request.url.params) == {
            "limit": "25",
            "offset": "0",
            "ticker": "AAPL",
            "status": "success",
        }
        body = TraceListResponse(traces=[], next_offset=None, risingwave_connected=True)
        return httpx.Response(200, content=body.model_dump_json())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        result = await fetch_trace_list(client, 25, 0, "AAPL", "success")

    assert isinstance(result, TraceListResponse)
    assert result.risingwave_connected is True


async def test_fetch_trace_detail_parses_real_contract_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/traces/abc-123"
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
        return httpx.Response(200, content=body.model_dump_json())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        result = await fetch_trace_detail(client, "abc-123")

    assert isinstance(result, TraceDetailResponse)
    assert result.app_trace_id == "abc-123"
    assert result.judge_state == "evaluated"


async def test_fetch_calibration_health_parses_real_contract_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/calibration/health"
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
        return httpx.Response(200, content=body.model_dump_json())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=METRICS_SERVICE_URL) as client:
        result = await fetch_calibration_health(client)

    assert isinstance(result, CalibrationHealthResponse)
    assert result.position == "between_thresholds"
