"""Tests for the /metrics/snapshot endpoint (Day 8 Gate A) -- the typed
MetricsSnapshot contract the gateway's SSE poller consumes."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import app


def _now() -> datetime.datetime:
    # _build_snapshot() computes `now` internally via datetime.now(UTC) at
    # call time -- a fixture anchored to a hardcoded date would drift against
    # that real clock. Anchor fixtures to the real clock instead.
    return datetime.datetime.now(datetime.UTC)


_FRESH = _now() - datetime.timedelta(seconds=30)
_STALE = _now() - datetime.timedelta(minutes=10)


def _fresh_metrics() -> dict[str, Any]:
    return {
        "throughput": {
            "total_requests": 10,
            "success_count": 9,
            "blocked_count": 1,
            "error_count": 0,
            "avg_latency_ms": 120.5,
            "p95_latency_ms": 300.0,
            "window_start": _FRESH - datetime.timedelta(minutes=1),
            "window_end": _FRESH,
        },
        "faithfulness": {
            "verdicts_count": 5,
            "avg_faithfulness": 0.9,
            "complete_count": 5,
            "skipped_count": 0,
            "window_start": _FRESH - datetime.timedelta(minutes=1),
            "window_end": _FRESH,
        },
        "relevance": None,
        "tokens": None,
        "cost": None,
        "risingwave_connected": True,
    }


async def _patched_snapshot_deps(
    metrics: dict[str, Any], frontier_latest_window_end: datetime.datetime | None
) -> Any:
    frontier = {
        "window_minutes": 15,
        "verdict_counts": {"frontier_pass": 2},
        "disagreement_counts": {"agreement": 2},
        "risingwave_connected": True,
    }
    return (
        patch("finsentry.dashboard.app._fetch_metrics", AsyncMock(return_value=metrics)),
        patch("finsentry.dashboard.app._fetch_frontier_metrics", AsyncMock(return_value=frontier)),
        patch(
            "finsentry.dashboard.app._fetch_frontier_latest_window_end",
            AsyncMock(return_value=frontier_latest_window_end),
        ),
    )


@pytest.mark.anyio
async def test_snapshot_marks_fresh_section_not_stale() -> None:
    p1, p2, p3 = await _patched_snapshot_deps(_fresh_metrics(), _FRESH)
    with p1, p2, p3:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/snapshot")

    assert resp.status_code == 200
    body = resp.json()
    assert body["throughput"]["stale"] is False
    assert body["faithfulness"]["stale"] is False
    assert body["relevance"] is None
    assert body["frontier"]["stale"] is False
    assert body["frontier"]["verdict_counts"]["frontier_pass"] == 2


@pytest.mark.anyio
async def test_snapshot_marks_old_window_as_stale() -> None:
    metrics = _fresh_metrics()
    metrics["throughput"]["window_end"] = _STALE
    p1, p2, p3 = await _patched_snapshot_deps(metrics, _STALE)
    with p1, p2, p3:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/snapshot")

    body = resp.json()
    assert body["throughput"]["stale"] is True
    assert body["frontier"]["stale"] is True


@pytest.mark.anyio
async def test_snapshot_frontier_with_no_recent_activity_is_conservatively_stale() -> None:
    """Zero frontier samples in the 15-minute lookback (latest_window_end is
    None) must not be reported as fresh just because verdict_counts is a
    valid empty dict -- there is no evidence either way, so stale=True."""
    p1, p2, p3 = await _patched_snapshot_deps(_fresh_metrics(), None)
    with p1, p2, p3:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/snapshot")

    body = resp.json()
    assert body["frontier"]["latest_window_end"] is None
    assert body["frontier"]["stale"] is True


@pytest.mark.anyio
async def test_snapshot_offline_mode_has_none_sections() -> None:
    offline_metrics = {
        "throughput": None,
        "faithfulness": None,
        "relevance": None,
        "tokens": None,
        "cost": None,
        "risingwave_connected": False,
    }
    p1, p2, p3 = await _patched_snapshot_deps(offline_metrics, None)
    with p1, p2, p3:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics/snapshot")

    body = resp.json()
    assert body["risingwave_connected"] is False
    assert body["throughput"] is None
    assert body["frontier"]["stale"] is True
