"""The incident API: typed, validated, and read-only except for the one route that starts a run.

A GET never starts an investigation, never calls the planner and never writes. The proof is a
planner and a tool session that fail the test if touched, plus row and event counts that do not
move. Everything returned is a stored value or derived from one.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from finsentry.investigator import store
from finsentry.investigator.api import build_router
from finsentry.investigator.evaluation import seed
from finsentry.investigator.service import InvestigationDeps
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.redteam.run_gate import HEADER
from tests.conftest import TEST_DATABASE_URL as URL
from tests.investigations.conftest import TEST_RUN_PASSWORD
from tests.investigations.helpers import ForbiddenPlanner, GatedPlanner, deps_for, settle, sql


@asynccontextmanager
async def _forbidden_tools() -> AsyncIterator[McpReadTools]:
    raise AssertionError("a read must never open the tool server")
    yield  # pragma: no cover


def _read_only_deps() -> InvestigationDeps:
    return InvestigationDeps(
        database_url=URL,
        planner_factory=ForbiddenPlanner,
        tool_session=_forbidden_tools,
    )


def _client(deps: InvestigationDeps) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(build_router(lambda: deps))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        headers={HEADER: TEST_RUN_PASSWORD},
    )


@pytest.fixture
async def seeded() -> dict[str, str]:
    return await seed.seed_all(URL, replace=True)


def counts() -> tuple[object, object, object]:
    return (
        sql("SELECT count(*) FROM investigations")[0][0],
        sql("SELECT count(*) FROM investigation_events")[0][0],
        sql("SELECT max(heartbeat_at) FROM investigations")[0][0],
    )


# A GET never runs anything.


async def test_reads_never_start_a_run_call_the_planner_or_write(seeded: dict[str, str]) -> None:
    deps = _read_only_deps()
    before = counts()
    async with _client(deps) as client:
        for _ in range(3):
            assert (await client.get("/ops/investigations")).status_code == 200
            for investigation_id in seeded.values():
                assert (
                    await client.get(f"/ops/investigations/{investigation_id}")
                ).status_code == 200
            assert (await client.get("/ops/investigations?status=completed")).status_code == 200
    assert counts() == before
    assert deps.tasks == set()


async def test_a_page_refresh_reopens_the_stored_report_and_starts_nothing(
    seeded: dict[str, str],
) -> None:
    deps = _read_only_deps()
    async with _client(deps) as client:
        first = (await client.get(f"/ops/investigations/{seeded['diagnosis']}")).json()
    async with _client(_read_only_deps()) as client:  # a new process
        second = (await client.get(f"/ops/investigations/{seeded['diagnosis']}")).json()
    assert first == second
    assert second["report"]["outcome"] == "diagnosis"
    assert sql("SELECT count(*) FROM investigations WHERE status = 'running'")[0][0] == 0


# What the reads return.


async def test_the_list_is_newest_first_and_labels_where_each_session_came_from(
    seeded: dict[str, str],
) -> None:
    async with _client(_read_only_deps()) as client:
        body = (await client.get("/ops/investigations?limit=50")).json()
    rows = body["investigations"]
    assert len(rows) == len(seeded) and body["next_offset"] is None
    assert [r["created_at"] for r in rows] == sorted((r["created_at"] for r in rows), reverse=True)
    assert {r["origin"] for r in rows} == {"fixture"}
    assert {r["planner"] for r in rows} == {"planner-double"}
    by_id = {r["investigation_id"]: r for r in rows}
    diagnosis = by_id[seeded["diagnosis"]]
    assert diagnosis["status"] == "completed" and diagnosis["outcome"] == "diagnosis"
    assert diagnosis["leading"]["subsystem"] == "judges"
    assert by_id[seeded["abstention"]]["leading"] is None
    assert by_id[seeded["failed"]]["status"] == "failed" and by_id[seeded["failed"]]["error"]
    assert by_id[seeded["interrupted"]]["status"] == "interrupted"
    # A session that stored no final state does not claim zero queries or hypotheses.
    assert by_id[seeded["interrupted"]]["queries"] is None
    assert by_id[seeded["interrupted"]]["hypotheses"] is None


async def test_a_detail_counts_the_queries_an_unfinished_session_made(
    seeded: dict[str, str],
) -> None:
    async with _client(_read_only_deps()) as client:
        interrupted = (await client.get(f"/ops/investigations/{seeded['interrupted']}")).json()
        failed = (await client.get(f"/ops/investigations/{seeded['failed']}")).json()
    assert interrupted["queries"] == 1 and interrupted["state"] is None
    assert failed["queries"] == 1 and failed["state"] is not None


async def test_the_list_filters_and_pages(seeded: dict[str, str]) -> None:
    async with _client(_read_only_deps()) as client:
        only = (await client.get("/ops/investigations?status=failed")).json()["investigations"]
        first = (await client.get("/ops/investigations?limit=2")).json()
        second = (await client.get("/ops/investigations?limit=2&offset=2")).json()
    assert [r["investigation_id"] for r in only] == [seeded["failed"]]
    assert len(first["investigations"]) == 2 and first["next_offset"] == 2
    assert {r["investigation_id"] for r in first["investigations"]}.isdisjoint(
        {r["investigation_id"] for r in second["investigations"]}
    )


async def test_the_detail_carries_the_timeline_state_report_and_usage(
    seeded: dict[str, str],
) -> None:
    async with _client(_read_only_deps()) as client:
        body = (await client.get(f"/ops/investigations/{seeded['diagnosis']}")).json()
    kinds = [e["event"]["kind"] for e in body["timeline"]]
    assert kinds[0] == "query" and kinds[-1] == "stopped"
    assert body["trigger"]["kind"] == "judge_disagreement_cluster"
    assert body["window"]["start"] < body["window"]["end"]
    assert body["state"]["executed_queries"] and body["state"]["hypotheses"]
    assert body["report"]["ranked_hypotheses"][0]["rank"] == 1
    assert body["usage"]["model"]["planner"] == "planner-double"
    assert body["usage"]["model"]["cost_usd"] == 0
    assert body["usage"]["budgets"]["max_tool_calls"] == 8
    assert body["stale"] is False


async def test_a_read_returns_no_hidden_truth_and_no_raw_request(seeded: dict[str, str]) -> None:
    async with _client(_read_only_deps()) as client:
        text = (await client.get(f"/ops/investigations/{seeded['diagnosis']}")).text
        listing = (await client.get("/ops/investigations")).text
    for word in ("expected_behavior", "true_subsystems", "cause_markers", "fixture_case"):
        assert word not in text and word not in listing


async def test_an_unknown_or_malformed_id_is_not_found() -> None:
    async with _client(_read_only_deps()) as client:
        missing = await client.get("/ops/investigations/00000000-0000-0000-0000-000000000000")
        malformed = await client.get("/ops/investigations/not-a-uuid")
    assert missing.status_code == 404 and malformed.status_code == 404
    assert missing.json() == {"error": "investigation not found"}


async def test_a_running_session_with_an_old_heartbeat_reads_as_stale_without_changing() -> None:
    investigation_id = "00000000-0000-0000-0000-0000000000aa"
    store.create(
        URL,
        investigation_id=investigation_id,
        incident_id="inc-x",
        origin="live",
        planner="p",
        agent_version="v",
        request={
            "kind": "drift_degradation",
            "window": {"start": "2026-10-01T11:00:00Z", "end": "2026-10-01T12:00:00Z"},
        },
        request_key="k",
    )
    sql(
        "UPDATE investigations SET heartbeat_at = %s WHERE investigation_id = %s",
        datetime.now(UTC) - timedelta(minutes=store.STALE_AFTER_MINUTES + 1),
        investigation_id,
    )
    async with _client(_read_only_deps()) as client:
        body = (await client.get(f"/ops/investigations/{investigation_id}")).json()
    assert body["status"] == "running" and body["stale"] is True
    assert sql("SELECT status FROM investigations")[0][0] == "running"


async def test_an_unreadable_store_is_a_short_json_error() -> None:
    deps = InvestigationDeps(
        database_url="postgresql://x:y@127.0.0.1:1/none",
        planner_factory=ForbiddenPlanner,
        tool_session=_forbidden_tools,
    )
    async with _client(deps) as client:
        listing = await client.get("/ops/investigations")
        detail = await client.get("/ops/investigations/00000000-0000-0000-0000-000000000000")
    for response in (listing, detail):
        assert response.status_code == 503
        assert response.json() == {"error": "investigation store unavailable"}


# Starting a run.


async def test_a_valid_start_is_accepted_stored_and_then_readable() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    async with _client(deps) as client:
        started = await client.post("/ops/investigations", json={"kind": "drift_degradation"})
        assert started.status_code == 202
        body = started.json()
        assert body["created"] is True and body["investigation"]["status"] == "running"
        assert body["investigation"]["origin"] == "live"
        investigation_id = body["investigation"]["investigation_id"]
        planner.release.set()
        await settle(deps)
        detail = (await client.get(f"/ops/investigations/{investigation_id}")).json()
    assert detail["status"] == "completed" and detail["report"] is not None
    assert detail["usage"]["used"]["inference_calls"] >= 1


async def test_the_same_start_twice_while_running_returns_the_same_session() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    async with _client(deps) as client:
        first = await client.post("/ops/investigations", json={"kind": "drift_degradation"})
        again = await client.post("/ops/investigations", json={"kind": "drift_degradation"})
        other = await client.post("/ops/investigations", json={"kind": "error_kind_surge"})
        planner.release.set()
        await settle(deps)
    assert first.status_code == 202 and again.status_code == 200
    assert again.json()["created"] is False
    assert (
        again.json()["investigation"]["investigation_id"]
        == first.json()["investigation"]["investigation_id"]
    )
    assert other.status_code == 409
    assert other.json()["investigation_id"] == first.json()["investigation"]["investigation_id"]
    assert sql("SELECT count(*) FROM investigations")[0][0] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"kind": "single_trace"},
        {"kind": "red_team_miss", "reference_id": "nope"},
        {"kind": "drift_degradation", "window_minutes": 0},
        {"kind": "drift_degradation", "window_minutes": 5000},
        {"kind": "bogus"},
        {"kind": "drift_degradation", "extra": 1},
    ],
)
async def test_an_invalid_start_is_rejected_before_anything_is_stored(
    body: dict[str, object],
) -> None:
    async with _client(deps_for("sparse-signal", GatedPlanner())) as client:
        response = await client.post("/ops/investigations", json=body)
    assert response.status_code == 422
    assert sql("SELECT count(*) FROM investigations")[0][0] == 0


async def test_a_start_with_no_model_configured_is_a_503_and_stores_nothing() -> None:
    async with _client(deps_for("sparse-signal", None)) as client:
        response = await client.post("/ops/investigations", json={"kind": "drift_degradation"})
    assert response.status_code == 503 and "error" in response.json()
    assert sql("SELECT count(*) FROM investigations")[0][0] == 0


async def test_the_start_route_cannot_choose_a_fixture_origin() -> None:
    planner = GatedPlanner()
    planner.release.set()
    deps = deps_for("sparse-signal", planner)
    async with _client(deps) as client:
        response = await client.post(
            "/ops/investigations", json={"kind": "drift_degradation", "origin": "fixture"}
        )
        assert response.status_code == 422
        started = await client.post("/ops/investigations", json={"kind": "drift_degradation"})
        await settle(deps)
    assert started.json()["investigation"]["origin"] == "live"
    await asyncio.sleep(0)


def test_the_gateway_mounts_the_three_investigation_routes() -> None:
    from finsentry.gateway.main import app

    paths = app.openapi()["paths"]
    assert sorted(paths["/ops/investigations"]) == ["get", "post"]
    assert list(paths["/ops/investigations/{investigation_id}"]) == ["get"]
