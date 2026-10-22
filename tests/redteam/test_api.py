"""Red Team API: validation, run lifecycle, history, evidence, and honest failure responses."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from finsentry.redteam import runner, store
from finsentry.redteam.api import build_router
from finsentry.redteam.classify import Observation
from finsentry.redteam.deps import Deps
from finsentry.redteam.run_gate import HEADER
from tests.conftest import TEST_DATABASE_URL
from tests.redteam.conftest import TEST_RUN_PASSWORD
from tests.redteam.helpers import make_deps

_CAUGHT = Observation(
    summary="Blocked.",
    evidence={"gateway_status": 403, "gateway_rail": "prompt-guard-2"},
    defense_acted=True,
    acting_layer="prompt-guard-2",
)
_DOWN = Observation(summary="", unavailable_reason="An input rail could not run.")


async def _fake_execute(scenario: object, deps: object, execution_id: str) -> Observation:
    return _DOWN if getattr(scenario, "id") == "HZ-001" else _CAUGHT


def _client(deps: Deps) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(build_router(lambda: deps))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://t",
        headers={HEADER: TEST_RUN_PASSWORD},
    )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with _client(make_deps()) as c:
        yield c


async def _finish_run(client: httpx.AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(200):
        body = (await client.get(f"/ops/redteam/runs/{run_id}")).json()
        if body["run"]["status"] != "running":
            return body  # type: ignore[no-any-return]
        await asyncio.sleep(0.02)
    raise AssertionError("run did not finish")


async def test_scenarios_lists_the_registry_with_no_result_before_any_run(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/ops/redteam/scenarios")).json()
    assert body["persistence_available"] is True
    assert len(body["scenarios"]) == 10
    first = body["scenarios"][0]
    assert first["expected"]["outcome"] == "caught"
    assert first["last_execution"] is None
    assert "query" in first["input"]


async def test_scenarios_still_lists_the_registry_when_the_store_is_down() -> None:
    dead = make_deps(database_url="postgresql://x:y@127.0.0.1:1/none")
    async with _client(dead) as c:
        body = (await c.get("/ops/redteam/scenarios")).json()
    assert body["persistence_available"] is False
    assert len(body["scenarios"]) == 10


async def test_a_run_lifecycle_persists_history_and_distinct_executions(
    client: httpx.AsyncClient,
) -> None:
    with patch.object(runner, "_execute", _fake_execute):
        started = await client.post(
            "/ops/redteam/runs", json={"scenario_ids": ["DI-001", "HZ-001"]}
        )
        assert started.status_code == 202
        queued = started.json()
        assert [e["scenario_id"] for e in queued["executions"]] == ["DI-001", "HZ-001"]
        assert {e["state"] for e in queued["executions"]} <= {"queued", "running"}
        assert all(e["outcome"] is None for e in queued["executions"])
        done = await _finish_run(client, queued["run"]["run_id"])
    outcomes = {e["scenario_id"]: e["outcome"] for e in done["executions"]}  # type: ignore[attr-defined]
    assert outcomes == {"DI-001": "caught", "HZ-001": "evaluator_unavailable"}
    assert done["run"]["outcome_counts"] == {"caught": 1, "evaluator_unavailable": 1}  # type: ignore[index]

    history = (await client.get("/ops/redteam/runs")).json()
    assert [r["run_id"] for r in history] == [queued["run"]["run_id"]]


async def test_an_unavailable_evaluator_is_returned_without_an_acting_layer(
    client: httpx.AsyncClient,
) -> None:
    with patch.object(runner, "_execute", _fake_execute):
        started = (await client.post("/ops/redteam/runs", json={"scenario_ids": ["HZ-001"]})).json()
        await _finish_run(client, started["run"]["run_id"])
    page = (
        await client.get("/ops/redteam/executions", params={"outcome": "evaluator_unavailable"})
    ).json()
    assert len(page["executions"]) == 1
    assert page["executions"][0]["acting_layer"] is None
    assert page["executions"][0]["expectation"] == "not_assessable"


async def test_executions_filter_by_category_outcome_scenario_and_run(
    client: httpx.AsyncClient,
) -> None:
    with patch.object(runner, "_execute", _fake_execute):
        first = (
            await client.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001", "OUT-001"]})
        ).json()
        await _finish_run(client, first["run"]["run_id"])
        second = (await client.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001"]})).json()
        await _finish_run(client, second["run"]["run_id"])

    async def ids(**params: str) -> list[str]:
        body = (await client.get("/ops/redteam/executions", params=params)).json()
        return [e["scenario_id"] for e in body["executions"]]

    assert await ids(scenario_id="DI-001") == ["DI-001", "DI-001"]
    assert await ids(category="output_schema") == ["OUT-001"]
    assert await ids(run_id=first["run"]["run_id"]) == ["DI-001", "OUT-001"]
    assert await ids(outcome="missed") == []


async def test_one_execution_returns_its_evidence_and_expected_apart(
    client: httpx.AsyncClient,
) -> None:
    with patch.object(runner, "_execute", _fake_execute):
        started = (await client.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001"]})).json()
        await _finish_run(client, started["run"]["run_id"])
    execution_id = started["executions"][0]["execution_id"]
    row = (await client.get(f"/ops/redteam/executions/{execution_id}")).json()
    assert row["expected"]["layer"] == "prompt-guard-2"
    assert row["outcome"] == "caught"
    assert row["evidence"]["gateway_rail"] == "prompt-guard-2"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"scenario_ids": ["NOPE-001"]}, 422),
        ({"scenario_ids": []}, 422),
        ({"scenario_ids": ["OUT-003"]}, 422),
        ({"scenario_ids": ["A-001"] * 13}, 422),
        ({"allow_judge_assisted": "maybe"}, 422),
    ],
)
async def test_invalid_run_requests_are_rejected(
    client: httpx.AsyncClient, body: dict[str, object], status: int
) -> None:
    resp = await client.post("/ops/redteam/runs", json=body)
    assert resp.status_code == status
    assert "Traceback" not in resp.text


async def test_a_rejected_run_leaves_no_rows(client: httpx.AsyncClient) -> None:
    await client.post("/ops/redteam/runs", json={"scenario_ids": ["NOPE-001"]})
    assert (await client.get("/ops/redteam/runs")).json() == []


async def test_a_second_run_while_one_is_active_answers_409_with_the_active_run_id(
    client: httpx.AsyncClient,
) -> None:
    release = asyncio.Event()

    async def slow(*_: object, **__: object) -> Observation:
        await release.wait()
        return _CAUGHT

    with patch.object(runner, "_execute", slow):
        first = (await client.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001"]})).json()
        second = await client.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001"]})
        assert second.status_code == 409
        assert second.json()["run_id"] == first["run"]["run_id"]
        release.set()
        await _finish_run(client, first["run"]["run_id"])


@pytest.mark.parametrize(
    "path",
    [
        "/ops/redteam/runs/not-a-uuid",
        "/ops/redteam/executions/not-a-uuid",
        "/ops/redteam/executions?category=bogus",
        "/ops/redteam/executions?outcome=bogus",
        "/ops/redteam/executions?limit=0",
        "/ops/redteam/executions?run_id=not-a-uuid",
        "/ops/redteam/runs?limit=500",
    ],
)
async def test_malformed_reads_answer_422_not_500(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 422


async def test_unknown_ids_answer_404(client: httpx.AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    for path in (f"/ops/redteam/runs/{missing}", f"/ops/redteam/executions/{missing}"):
        resp = await client.get(path)
        assert resp.status_code == 404 and "error" in resp.json()


async def test_a_dead_store_answers_503_with_a_short_error_and_no_detail() -> None:
    dead = make_deps(database_url="postgresql://user:secret@127.0.0.1:1/none")
    async with _client(dead) as c:
        for resp in (
            await c.get("/ops/redteam/runs"),
            await c.get("/ops/redteam/executions"),
            await c.post("/ops/redteam/runs", json={"scenario_ids": ["DI-001"]}),
        ):
            assert resp.status_code == 503
            assert resp.json() == {"error": "red team store unavailable"}
            assert "secret" not in resp.text


async def test_a_run_survives_being_read_after_the_store_returns() -> None:
    assert store.list_runs(TEST_DATABASE_URL, 5) == []


def test_the_gateway_app_mounts_the_red_team_routes_and_keeps_the_ops_routes() -> None:
    from finsentry.gateway.main import app

    # Included routers are wrapped lazily, so the OpenAPI schema is the reliable listing.
    paths = set(app.openapi()["paths"])
    assert {
        "/ops/redteam/scenarios",
        "/ops/redteam/runs",
        "/ops/redteam/runs/{run_id}",
        "/ops/redteam/executions",
        "/ops/redteam/executions/{execution_id}",
    } <= paths
    assert {"/ops/traces", "/ops/traces/{app_trace_id}", "/ops/stream", "/v1/rag/query"} <= paths
