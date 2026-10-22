"""The password gate in front of POST /ops/investigations. A refusal opens no session, writes no
timeline event, builds no planner and opens no tool session. Reads need no password."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from finsentry.investigator.api import build_router
from finsentry.investigator.evaluation import seed
from finsentry.investigator.service import InvestigationDeps
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.redteam.run_gate import HEADER, MAX_FAILURES, PASSWORD_ENV
from tests.conftest import TEST_DATABASE_URL as URL
from tests.investigations.conftest import TEST_RUN_PASSWORD
from tests.investigations.helpers import sql

_BODY = {"kind": "drift_degradation"}


class _TouchedError(Exception):
    pass


class _Probe:
    """Deps whose planner factory and tool session record any use, so a refusal can prove it
    reached neither."""

    def __init__(self) -> None:
        self.planner_built = 0
        self.tools_opened = 0

    def _planner(self) -> object:
        self.planner_built += 1
        raise _TouchedError("the planner factory ran")

    @asynccontextmanager
    async def _tools(self) -> AsyncIterator[McpReadTools]:
        self.tools_opened += 1
        raise _TouchedError("the tool session opened")
        yield  # pragma: no cover

    def deps(self) -> InvestigationDeps:
        return InvestigationDeps(
            database_url=URL,
            planner_factory=self._planner,  # type: ignore[arg-type]
            tool_session=self._tools,
        )


@pytest.fixture
def probe() -> _Probe:
    return _Probe()


@pytest.fixture
async def bare(probe: _Probe) -> AsyncIterator[httpx.AsyncClient]:
    """A client that sends no password unless a test adds one."""
    app = FastAPI()
    app.include_router(build_router(probe.deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _nothing_written(probe: _Probe) -> None:
    assert sql("SELECT count(*) FROM investigations")[0][0] == 0
    assert sql("SELECT count(*) FROM investigation_events")[0][0] == 0
    assert (probe.planner_built, probe.tools_opened) == (0, 0)


@pytest.mark.parametrize("password", [None, "", "wrong-password", TEST_RUN_PASSWORD + "x"])
async def test_a_missing_or_wrong_password_is_refused_and_writes_nothing(
    bare: httpx.AsyncClient, probe: _Probe, password: str | None
) -> None:
    headers = {} if password is None else {HEADER: password}
    resp = await bare.post("/ops/investigations", json=_BODY, headers=headers)
    assert resp.status_code == 401
    assert resp.json() == {"error": "The run password is missing or incorrect."}
    _nothing_written(probe)


async def test_a_refusal_comes_before_the_store_is_read(
    bare: httpx.AsyncClient, probe: _Probe
) -> None:
    # A running session would make a valid start answer 200 or 409. Without the password the
    # answer is the auth error, which shows the store was never consulted.
    resp = await bare.post("/ops/investigations", json={"kind": "error_kind_surge"})
    assert resp.status_code == 401
    _nothing_written(probe)


async def test_the_correct_password_passes_the_gate_and_reaches_the_start_path(
    probe: _Probe,
) -> None:
    # With no planner factory the start path answers 503 after the gate and before any write,
    # so this proves acceptance without running an investigation.
    deps = InvestigationDeps(database_url=URL, planner_factory=None, tool_session=probe._tools)
    app = FastAPI()
    app.include_router(build_router(lambda: deps))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/ops/investigations", json=_BODY, headers={HEADER: TEST_RUN_PASSWORD})
    assert resp.status_code == 503
    assert "No model is configured" in resp.json()["error"]
    _nothing_written(probe)


async def test_with_no_password_configured_every_start_is_refused(
    bare: httpx.AsyncClient, probe: _Probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(PASSWORD_ENV)
    for supplied in ("", "anything", TEST_RUN_PASSWORD):
        resp = await bare.post("/ops/investigations", json=_BODY, headers={HEADER: supplied})
        assert resp.status_code == 503
        assert "disabled" in resp.json()["error"]
    _nothing_written(probe)


async def test_repeated_failures_lock_the_gate_even_for_the_correct_password(
    bare: httpx.AsyncClient, probe: _Probe
) -> None:
    for _ in range(MAX_FAILURES):
        resp = await bare.post("/ops/investigations", json=_BODY, headers={HEADER: "nope"})
        assert resp.status_code == 401
    locked = await bare.post("/ops/investigations", json=_BODY, headers={HEADER: TEST_RUN_PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    _nothing_written(probe)


async def test_failures_on_the_run_route_also_lock_the_investigation_route(
    bare: httpx.AsyncClient, probe: _Probe
) -> None:
    # One failure count guards both start routes, so guessing against either spends the same
    # budget and a second route does not double the number of guesses.
    from finsentry.redteam.run_gate import run_gate

    for _ in range(MAX_FAILURES):
        assert run_gate.check("nope").status == 401
    locked = await bare.post("/ops/investigations", json=_BODY, headers={HEADER: TEST_RUN_PASSWORD})
    assert locked.status_code == 429
    _nothing_written(probe)


async def test_reads_need_no_password(bare: httpx.AsyncClient, probe: _Probe) -> None:
    seeded = await seed.seed_all(URL, replace=True)
    listing = await bare.get("/ops/investigations")
    assert listing.status_code == 200
    one = await bare.get(f"/ops/investigations/{next(iter(seeded.values()))}")
    assert one.status_code == 200
    assert (probe.planner_built, probe.tools_opened) == (0, 0)


def test_the_gateway_documents_the_password_header_on_the_start_route() -> None:
    from finsentry.gateway.main import app

    post = app.openapi()["paths"]["/ops/investigations"]["post"]
    assert HEADER.lower() in [p["name"].lower() for p in post["parameters"]]
