"""Tests for finsentry.dashboard.app."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import (
    _fmt,
    _fmt_cost,
    _render_html,
    _skip_rate,
    _success_rate,
    _to_jsonable,
    app,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_metrics(
    throughput: dict[str, Any] | None = None,
    faithfulness: dict[str, Any] | None = None,
    relevance: dict[str, Any] | None = None,
    tokens: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
    connected: bool = False,
) -> dict[str, Any]:
    return {
        "throughput": throughput,
        "faithfulness": faithfulness,
        "relevance": relevance,
        "tokens": tokens,
        "cost": cost,
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


def test_fmt_cost_formats_usd_with_six_decimal_places() -> None:
    assert _fmt_cost(0.000123) == "$0.000123"
    assert _fmt_cost(None) == "—"
    assert _fmt_cost(0.0) == "$0.000000"


def test_to_jsonable_converts_nested_decimals() -> None:
    import json
    from decimal import Decimal
    payload = {
        "throughput": {"avg_latency_ms": Decimal("32150.0"), "total_requests": 2},
        "cost": {"cost_total_usd": Decimal("0.016583")},
        "nested_list": [Decimal("1.5"), {"x": Decimal("2.5")}],
        "passthrough": "ok",
    }
    out = _to_jsonable(payload)
    json.dumps(out)  # must not raise
    assert out["throughput"]["avg_latency_ms"] == 32150.0
    assert isinstance(out["throughput"]["avg_latency_ms"], float)
    assert out["cost"]["cost_total_usd"] == 0.016583
    assert out["nested_list"][1]["x"] == 2.5
    assert out["passthrough"] == "ok"
