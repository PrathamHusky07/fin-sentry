"""
MetricsPoller: the one background task per gateway process that polls the
metrics service (via finsentry.gateway.metrics_client.fetch_snapshot) on a
fixed interval and holds the latest MetricsSnapshot in memory, broadcasting
it to every SSE client connected to this process.

Query load scales with gateway replica count, never with browser-connection
count: N clients on one replica share one poller and one upstream HTTP call
per interval, not N separate polls. Fan-out to subscribers is a plain
in-process set of bounded asyncio.Queue objects -- not a broker, not a
pub/sub service; there is nothing here reusable beyond this one poller.

Lifecycle-owned: created and started in the gateway's FastAPI lifespan,
stopped there too (see finsentry/gateway/main.py). Never created at module
import time, never created per SSE connection -- one instance per process,
same as the RisingWave pools in finsentry/mcp/state.py and
finsentry/dashboard/app.py are one instance per their own owning process.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging

import httpx

from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.gateway.metrics_client import fetch_snapshot

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: float = 3.0
_SUBSCRIBER_QUEUE_MAXSIZE = 1


def unavailable_snapshot(now: datetime.datetime) -> MetricsSnapshot:
    """The honest snapshot when the metrics service can't be reached at
    all -- never fabricated zeros, an explicit unreachable state with every
    section absent. (A snapshot the metrics service DID return, but which
    itself says risingwave_connected=False, is passed through unchanged --
    its None sections and stale frontier flag already say this honestly.)
    """
    return MetricsSnapshot(generated_at=now, risingwave_connected=False)


class MetricsPoller:
    def __init__(
        self, client: httpx.AsyncClient, interval_seconds: float = POLL_INTERVAL_SECONDS
    ) -> None:
        self._client = client
        self._interval = interval_seconds
        self._latest: MetricsSnapshot = unavailable_snapshot(datetime.datetime.now(datetime.UTC))
        self._subscribers: set[asyncio.Queue[MetricsSnapshot]] = set()
        self._task: asyncio.Task[None] | None = None

    @property
    def latest(self) -> MetricsSnapshot:
        return self._latest

    def subscribe(self) -> asyncio.Queue[MetricsSnapshot]:
        """Register a new SSE client. It immediately receives whatever the
        poller currently holds -- it never waits a full interval for its
        first snapshot."""
        queue: asyncio.Queue[MetricsSnapshot] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        queue.put_nowait(self._latest)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[MetricsSnapshot]) -> None:
        self._subscribers.discard(queue)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                snapshot = await fetch_snapshot(self._client)
            except Exception:
                log.warning(
                    "metrics service unreachable -- emitting an unavailable snapshot",
                    exc_info=True,
                )
                snapshot = unavailable_snapshot(datetime.datetime.now(datetime.UTC))
            self._latest = snapshot
            self._broadcast(snapshot)
            await asyncio.sleep(self._interval)

    def _broadcast(self, snapshot: MetricsSnapshot) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # Subscribers only ever want the latest snapshot, never a
                # backlog -- drop whatever they haven't read yet.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(snapshot)
