"""The Red Team run password gate: refusals start nothing, the correct password reaches the
existing run path, an unset password fails closed and repeated failures are rate limited."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from finsentry.redteam import runner
from finsentry.redteam.api import build_router
from finsentry.redteam.classify import Observation
from finsentry.redteam.run_gate import (
    HEADER,
    MAX_FAILURES,
    PASSWORD_ENV,
    WINDOW_SECONDS,
    RunGate,
)
from tests.conftest import TEST_DATABASE_URL
from tests.redteam.conftest import TEST_RUN_PASSWORD
from tests.redteam.helpers import make_deps

_BODY = {"scenario_ids": ["DI-001"]}
_CAUGHT = Observation(summary="Blocked.", evidence={}, defense_acted=True, acting_layer="x")


@pytest.fixture
async def bare() -> AsyncIterator[httpx.AsyncClient]:
    """A client that sends no password unless a test adds one."""
    app = FastAPI()
    app.include_router(build_router(lambda: make_deps()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _row_counts() -> tuple[int, int]:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        runs = conn.execute("SELECT count(*) FROM red_team_runs").fetchone()
        executions = conn.execute("SELECT count(*) FROM red_team_executions").fetchone()
    assert runs is not None and executions is not None
    return int(runs[0]), int(executions[0])


@pytest.mark.parametrize("password", [None, "", "wrong-password", TEST_RUN_PASSWORD + "x"])
async def test_a_missing_or_wrong_password_is_refused_and_starts_nothing(
    bare: httpx.AsyncClient, password: str | None
) -> None:
    headers = {} if password is None else {HEADER: password}
    with patch("finsentry.redteam.api.start_run", new_callable=AsyncMock) as started:
        resp = await bare.post("/ops/redteam/runs", json=_BODY, headers=headers)
    assert resp.status_code == 401
    assert resp.json() == {"error": "The run password is missing or incorrect."}
    started.assert_not_awaited()
    assert _row_counts() == (0, 0)


async def test_a_refusal_happens_before_the_request_body_is_resolved(
    bare: httpx.AsyncClient,
) -> None:
    # An unknown scenario id would be a 400 from the runner. Without the password it must
    # not get that far, so the answer is the auth error and nothing is created.
    resp = await bare.post("/ops/redteam/runs", json={"scenario_ids": ["NOPE-001"]})
    assert resp.status_code == 401
    assert _row_counts() == (0, 0)


async def test_the_correct_password_reaches_the_existing_run_path(
    bare: httpx.AsyncClient,
) -> None:
    async def execute(scenario: object, deps: object, execution_id: str) -> Observation:
        return _CAUGHT

    with patch.object(runner, "_execute", execute):
        resp = await bare.post("/ops/redteam/runs", json=_BODY, headers={HEADER: TEST_RUN_PASSWORD})
        assert resp.status_code == 202
        run_id = resp.json()["run"]["run_id"]
        for _ in range(200):
            detail = (await bare.get(f"/ops/redteam/runs/{run_id}")).json()
            if detail["run"]["status"] != "running":
                break
            await asyncio.sleep(0.02)
    assert detail["run"]["status"] == "completed"
    assert _row_counts() == (1, 1)


async def test_with_no_password_configured_every_run_is_refused(
    bare: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(PASSWORD_ENV)
    assert (await bare.get("/ops/redteam/run-gate")).json() == {"runs_enabled": False}
    with patch("finsentry.redteam.api.start_run", new_callable=AsyncMock) as started:
        for supplied in ("", "anything", TEST_RUN_PASSWORD):
            resp = await bare.post("/ops/redteam/runs", json=_BODY, headers={HEADER: supplied})
            assert resp.status_code == 503
            assert "disabled" in resp.json()["error"]
    started.assert_not_awaited()
    assert _row_counts() == (0, 0)


async def test_an_empty_password_variable_counts_as_unset(
    bare: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "")
    assert (await bare.get("/ops/redteam/run-gate")).json() == {"runs_enabled": False}
    resp = await bare.post("/ops/redteam/runs", json=_BODY, headers={HEADER: ""})
    assert resp.status_code == 503


async def test_the_run_gate_route_reports_enabled_and_reveals_nothing_else(
    bare: httpx.AsyncClient,
) -> None:
    resp = await bare.get("/ops/redteam/run-gate")
    assert resp.json() == {"runs_enabled": True}
    assert TEST_RUN_PASSWORD not in resp.text


async def test_repeated_failures_lock_the_gate_even_for_the_correct_password(
    bare: httpx.AsyncClient,
) -> None:
    with patch("finsentry.redteam.api.start_run", new_callable=AsyncMock) as started:
        for _ in range(MAX_FAILURES):
            resp = await bare.post("/ops/redteam/runs", json=_BODY, headers={HEADER: "nope"})
            assert resp.status_code == 401
        locked = await bare.post(
            "/ops/redteam/runs", json=_BODY, headers={HEADER: TEST_RUN_PASSWORD}
        )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    started.assert_not_awaited()
    assert _row_counts() == (0, 0)


async def test_the_password_is_never_logged_or_echoed(
    bare: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    attempt = "guess-4711"
    with caplog.at_level(logging.DEBUG):
        resp = await bare.post("/ops/redteam/runs", json=_BODY, headers={HEADER: attempt})
    assert attempt not in resp.text
    assert attempt not in caplog.text
    assert TEST_RUN_PASSWORD not in caplog.text


def test_a_lockout_lifts_when_the_oldest_failure_ages_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "right-one")
    now = [1000.0]
    gate = RunGate(clock=lambda: now[0])
    for _ in range(MAX_FAILURES):
        assert gate.check("bad").status == 401
    assert gate.check("right-one").status == 429
    now[0] += WINDOW_SECONDS - 1
    assert gate.check("right-one").status == 429
    now[0] += 2
    assert gate.check("right-one").allowed is True


def test_a_correct_password_clears_earlier_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "right-one")
    gate = RunGate(clock=lambda: 5.0)
    for _ in range(MAX_FAILURES - 1):
        gate.check("bad")
    assert gate.check("right-one").allowed is True
    for _ in range(MAX_FAILURES - 1):
        assert gate.check("bad").status == 401
    assert gate.check("right-one").allowed is True
