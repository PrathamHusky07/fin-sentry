"""Tests for finsentry.dashboard.app."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import _fmt, _render_html, _skip_rate, _success_rate, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_metrics(
    throughput: dict[str, Any] | None = None,
    faithfulness: dict[str, Any] | None = None,
    relevance: dict[str, Any] | None = None,
    tokens: dict[str, Any] | None = None,
    connected: bool = False,
) -> dict[str, Any]:
    return {
        "throughput": throughput,
        "faithfulness": faithfulness,
        "relevance": relevance,
        "tokens": tokens,
        "risingwave_connected": connected,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_health_endpoint_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_metrics_endpoint_returns_json() -> None:
    mock_data = _mock_metrics(
        throughput={"total_requests": 42, "success_count": 40, "blocked_count": 1,
                    "error_count": 1, "avg_latency_ms": 123.4, "p95_latency_ms": 456.7},
        connected=True,
    )
    with patch("finsentry.dashboard.app._fetch_metrics", AsyncMock(return_value=mock_data)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risingwave_connected"] is True
    assert body["throughput"]["total_requests"] == 42


@pytest.mark.anyio
async def test_dashboard_root_returns_html() -> None:
    mock_data = _mock_metrics()
    with patch("finsentry.dashboard.app._fetch_metrics", AsyncMock(return_value=mock_data)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "FinSentry" in resp.text


@pytest.mark.anyio
async def test_dashboard_shows_offline_badge_when_not_connected() -> None:
    mock_data = _mock_metrics(connected=False)
    with patch("finsentry.dashboard.app._fetch_metrics", AsyncMock(return_value=mock_data)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
    assert "offline" in resp.text.lower()


@pytest.mark.anyio
async def test_dashboard_shows_connected_badge_when_connected() -> None:
    mock_data = _mock_metrics(connected=True)
    with patch("finsentry.dashboard.app._fetch_metrics", AsyncMock(return_value=mock_data)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
    assert "connected" in resp.text.lower()


def test_render_html_handles_all_none_data() -> None:
    """_render_html should not raise when all metrics are None (offline mode)."""
    data = _mock_metrics()
    html = _render_html(data)
    assert "FinSentry" in html
    # All values should render as "—" sentinel
    assert "—" in html


def test_fmt_returns_na_on_none() -> None:
    assert _fmt(None) == "—"
    assert _fmt(None, suffix="%", na="N/A") == "N/A"


def test_success_rate_computes_correctly() -> None:
    tp = {"total_requests": 100, "success_count": 95}
    assert _success_rate(tp) == "95.0%"


def test_skip_rate_returns_dash_on_zero_verdicts() -> None:
    fa = {"verdicts_count": 0, "skipped_count": 0}
    assert _skip_rate(fa) == "—"
