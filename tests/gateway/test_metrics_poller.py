"""Tests for finsentry.gateway.metrics_poller.MetricsPoller -- one poller
per gateway process, broadcasting to every subscribed SSE client without
re-polling per client."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

import finsentry.gateway.metrics_poller as poller_module
from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.gateway.metrics_poller import MetricsPoller, unavailable_snapshot

_FAST_INTERVAL = 0.02


def _snapshot(connected: bool = True) -> MetricsSnapshot:
    return MetricsSnapshot(
        generated_at=datetime.datetime.now(datetime.UTC), risingwave_connected=connected
    )


@pytest.fixture()
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


async def test_subscriber_immediately_gets_the_current_snapshot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    poller = MetricsPoller(client, interval_seconds=_FAST_INTERVAL)
    queue = poller.subscribe()

    assert queue.get_nowait() == poller.latest


async def test_poller_broadcasts_real_fetch_to_all_subscribers(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_snapshot = _snapshot(connected=True)
    monkeypatch.setattr(poller_module, "fetch_snapshot", AsyncMock(return_value=real_snapshot))

    poller = MetricsPoller(client, interval_seconds=_FAST_INTERVAL)
    q1 = poller.subscribe()
    q2 = poller.subscribe()
    q1.get_nowait()  # drain the immediate placeholder each subscribe() delivers
    q2.get_nowait()

    await poller.start()
    try:
        received_1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        received_2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    finally:
        await poller.stop()

    assert received_1 == real_snapshot
    assert received_2 == real_snapshot
    assert poller.latest == real_snapshot


async def test_poller_emits_unavailable_snapshot_on_fetch_failure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        poller_module, "fetch_snapshot", AsyncMock(side_effect=httpx.ConnectError("refused"))
    )

    poller = MetricsPoller(client, interval_seconds=_FAST_INTERVAL)
    queue = poller.subscribe()
    queue.get_nowait()

    await poller.start()
    try:
        received = await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await poller.stop()

    assert received.risingwave_connected is False
    assert received.throughput is None


async def test_unavailable_snapshot_never_fabricates_data() -> None:
    now = datetime.datetime.now(datetime.UTC)
    snapshot = unavailable_snapshot(now)

    assert snapshot.risingwave_connected is False
    assert snapshot.throughput is None
    assert snapshot.faithfulness is None
    assert snapshot.relevance is None
    assert snapshot.tokens is None
    assert snapshot.cost is None
    assert snapshot.frontier is None


async def test_unsubscribe_stops_further_broadcasts(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(poller_module, "fetch_snapshot", AsyncMock(return_value=_snapshot()))

    poller = MetricsPoller(client, interval_seconds=_FAST_INTERVAL)
    queue = poller.subscribe()
    poller.unsubscribe(queue)

    await poller.start()
    await asyncio.sleep(_FAST_INTERVAL * 3)
    await poller.stop()

    assert queue.qsize() <= 1  # only the immediate placeholder from subscribe(), never a broadcast


async def test_stop_cancels_the_background_task_cleanly(client: httpx.AsyncClient) -> None:
    poller = MetricsPoller(client, interval_seconds=_FAST_INTERVAL)
    await poller.start()
    await poller.stop()

    assert poller._task is None
