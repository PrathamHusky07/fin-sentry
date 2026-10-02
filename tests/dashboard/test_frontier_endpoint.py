"""Tests for the /metrics/frontier endpoint in finsentry.dashboard.app."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import app


@pytest.mark.anyio
async def test_frontier_metrics_endpoint_returns_verdict_and_disagreement_counts() -> None:
    mock_data = {
        "window_minutes": 15,
        "verdict_counts": {"frontier_pass": 3, "frontier_degraded": 1},
        "disagreement_counts": {"agreement": 3, "insufficient_judges": 1},
        "risingwave_connected": True,
    }
    with patch(
        "finsentry.dashboard.app._fetch_frontier_metrics", AsyncMock(return_value=mock_data)
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/frontier")

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict_counts"]["frontier_pass"] == 3
    assert body["disagreement_counts"]["agreement"] == 3
    assert body["window_minutes"] == 15
    assert body["risingwave_connected"] is True


@pytest.mark.anyio
async def test_frontier_metrics_converts_decimal_counts_to_jsonable() -> None:
    mock_data = {
        "window_minutes": 15,
        "verdict_counts": {"frontier_pass": Decimal("3")},
        "disagreement_counts": {"agreement": Decimal("3")},
        "risingwave_connected": True,
    }
    with patch(
        "finsentry.dashboard.app._fetch_frontier_metrics", AsyncMock(return_value=mock_data)
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/frontier")

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict_counts"]["frontier_pass"] == 3.0


@pytest.mark.anyio
async def test_frontier_metrics_offline_mode_returns_empty_counts() -> None:
    mock_data = {
        "window_minutes": 15,
        "verdict_counts": {},
        "disagreement_counts": {},
        "risingwave_connected": False,
    }
    with patch(
        "finsentry.dashboard.app._fetch_frontier_metrics", AsyncMock(return_value=mock_data)
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/frontier")

    assert resp.status_code == 200
    body = resp.json()
    assert body["risingwave_connected"] is False
    assert body["verdict_counts"] == {}
