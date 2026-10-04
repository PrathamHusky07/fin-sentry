"""Tests for GET /ops/stream -- the gateway's SSE snapshot relay.

httpx's ASGITransport buffers the entire ASGI response body before
`handle_async_request` returns (see httpx/_transports/asgi.py: it awaits
the whole `self.app(...)` call before constructing a Response) -- it cannot
stream an infinite generator, which is exactly what a real SSE route is.
So the route-wiring tests below (status codes, headers) use the full ASGI
app, and the actual frame/keep-alive/unsubscribe behavior of
_ops_stream_events is tested directly as an async generator. The real,
infinite, over-the-wire behavior is proven against the live stack in Gate
C's curl + Playwright evidence, not here.
"""

from __future__ import annotations

import asyncio
import datetime

import pytest
from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.gateway.main import _ops_stream_events, app
from finsentry.gateway.metrics_poller import MetricsPoller


@pytest.fixture(autouse=True)
def _reset_poller() -> None:
    gw._metrics_poller = None


async def test_ops_stream_returns_503_when_poller_not_initialised() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/stream")

    assert resp.status_code == 503


async def test_ops_stream_relays_a_real_snapshot_frame() -> None:
    queue: asyncio.Queue[MetricsSnapshot] = asyncio.Queue(maxsize=1)
    snapshot = MetricsSnapshot(
        generated_at=datetime.datetime.now(datetime.UTC), risingwave_connected=True
    )
    queue.put_nowait(snapshot)

    gen = _ops_stream_events(queue)
    try:
        frame = (await gen.__anext__()).decode()
    finally:
        await gen.aclose()

    assert frame.startswith("event: snapshot\n")
    assert '"risingwave_connected":true' in frame


async def test_ops_stream_emits_keepalive_when_queue_is_idle() -> None:
    queue: asyncio.Queue[MetricsSnapshot] = asyncio.Queue(maxsize=1)

    original_timeout = gw._SSE_KEEPALIVE_TIMEOUT_SECONDS
    gw._SSE_KEEPALIVE_TIMEOUT_SECONDS = 0.02
    gen = _ops_stream_events(queue)
    try:
        frame = await gen.__anext__()
    finally:
        await gen.aclose()
        gw._SSE_KEEPALIVE_TIMEOUT_SECONDS = original_timeout

    assert frame == b": keep-alive\n\n"


async def test_ops_stream_generator_unsubscribes_on_close() -> None:
    poller = MetricsPoller.__new__(MetricsPoller)
    poller._subscribers = set()
    gw._metrics_poller = poller

    queue: asyncio.Queue[MetricsSnapshot] = asyncio.Queue(maxsize=1)
    poller._subscribers.add(queue)

    gen = _ops_stream_events(queue)
    # Advance the generator to its first await point, then close it --
    # simulating a client disconnect mid-stream.
    task = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await gen.aclose()

    assert queue not in poller._subscribers
