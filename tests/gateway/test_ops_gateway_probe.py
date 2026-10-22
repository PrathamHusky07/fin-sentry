"""The gateway's /ops/gateway-probe/latest route: it serves the stored probe summary as is, and a
failed or unconfigured read is a 503, never an empty summary that looks like no data."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import psycopg
from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.gateway.main import app
from finsentry.observability.gateway_probe import GatewayProbeRun, GatewayProbeSummary

_MEASURED = datetime.datetime(2026, 10, 22, 22, 40, tzinfo=datetime.UTC)


def _summary() -> GatewayProbeSummary:
    return GatewayProbeSummary(
        latest=GatewayProbeRun(
            measured_at=_MEASURED,
            target="http://localhost:8000/health",
            samples=30,
            median_ms=9.8,
            p95_ms=14.2,
            max_ms=21.0,
        ),
        runs_recorded=2,
    )


async def _get() -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/ops/gateway-probe/latest")
    return resp.status_code, resp.json()


async def test_serves_the_stored_summary() -> None:
    with (
        patch.object(gw, "_DATABASE_URL", "postgresql://stub"),
        patch.object(gw, "latest_summary", return_value=_summary()),
    ):
        status, body = await _get()

    assert status == 200
    assert body["runs_recorded"] == 2
    latest = body["latest"]
    assert isinstance(latest, dict)
    assert latest["median_ms"] == 9.8
    assert latest["target"] == "http://localhost:8000/health"


async def test_reports_no_run_as_a_null_latest() -> None:
    empty = GatewayProbeSummary(latest=None, runs_recorded=0)
    with (
        patch.object(gw, "_DATABASE_URL", "postgresql://stub"),
        patch.object(gw, "latest_summary", return_value=empty),
    ):
        status, body = await _get()

    assert status == 200
    assert body == {"latest": None, "runs_recorded": 0}


async def test_is_a_503_when_the_store_cannot_be_read() -> None:
    with (
        patch.object(gw, "_DATABASE_URL", "postgresql://stub"),
        patch.object(gw, "latest_summary", side_effect=psycopg.OperationalError("down")),
    ):
        status, _ = await _get()
    assert status == 503


async def test_is_a_503_when_no_database_is_configured() -> None:
    with patch.object(gw, "_DATABASE_URL", ""):
        status, _ = await _get()
    assert status == 503
