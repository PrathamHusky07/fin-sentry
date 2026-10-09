"""
The Red Team Console API, mounted on the gateway under /ops/redteam so the browser
reaches it through the same-origin /ops rewrite the other console routes use.

Routes: list scenarios, start a bounded run, list run history, read one run with its
executions, list executions with filters, read one execution's evidence. Errors are
short JSON with an `error` field. Nothing here returns a stack trace, a secret or raw
model output.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Annotated

import psycopg
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from finsentry.redteam import store
from finsentry.redteam.deps import Deps
from finsentry.redteam.models import Category, Outcome
from finsentry.redteam.records import (
    ExecutionList,
    ExecutionRecord,
    RunDetail,
    RunRecord,
    RunRequest,
)
from finsentry.redteam.registry import load_scenarios
from finsentry.redteam.runner import RunRejectedError, start_run

log = logging.getLogger(__name__)

_MAX_PAGE = 100


class ScenarioView(BaseModel):
    id: str
    version: int
    title: str
    category: Category
    target_layer: str
    description: str
    executor: str
    mode: str
    expected: dict[str, object]
    required_evidence: list[str]
    severity: str
    severity_rationale: str
    # The controlled input, harmless by construction, shown so an operator can read
    # exactly what a scenario fires.
    input: dict[str, object]
    last_execution: ExecutionRecord | None


class ScenarioList(BaseModel):
    scenarios: list[ScenarioView]
    # False when the store could not be read, so last_execution is unknown, not absent.
    persistence_available: bool


def _unavailable() -> JSONResponse:
    return JSONResponse({"error": "red team store unavailable"}, status_code=503)


def build_router(get_deps: Callable[[], Deps]) -> APIRouter:
    router = APIRouter(prefix="/ops/redteam")

    @router.get("/scenarios", response_model=ScenarioList)
    async def list_scenarios() -> Response:
        deps = get_deps()
        latest: dict[str, ExecutionRecord] = {}
        available = bool(deps.database_url)
        if available:
            try:
                latest = await asyncio.to_thread(
                    store.latest_finished_per_scenario, deps.database_url
                )
            except psycopg.Error:
                log.warning("red team store unreadable for the scenario list", exc_info=True)
                available = False
        views = [
            ScenarioView(
                **s.model_dump(mode="json", exclude={"input", "expected"}),
                expected=s.expected.model_dump(mode="json"),
                input=s.input.model_dump(mode="json"),
                last_execution=latest.get(s.id),
            )
            for s in load_scenarios()
        ]
        return JSONResponse(
            ScenarioList(scenarios=views, persistence_available=available).model_dump(mode="json")
        )

    @router.post("/runs", response_model=RunDetail, status_code=202)
    async def create_run(request: RunRequest) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            run_id = await start_run(request, deps)
            found = await asyncio.to_thread(store.get_run, deps.database_url, run_id)
        except RunRejectedError as rejected:
            body: dict[str, object] = {"error": rejected.message}
            if rejected.run_id:
                body["run_id"] = rejected.run_id
            return JSONResponse(body, status_code=rejected.status)
        except psycopg.Error:
            log.warning("red team store failed while starting a run", exc_info=True)
            return _unavailable()
        if found is None:
            return _unavailable()
        return JSONResponse(
            RunDetail(run=found[0], executions=found[1]).model_dump(mode="json"), status_code=202
        )

    @router.get("/runs", response_model=list[RunRecord])
    async def list_runs(limit: Annotated[int, Query(ge=1, le=50)] = 20) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            runs = await asyncio.to_thread(store.list_runs, deps.database_url, limit)
        except psycopg.Error:
            log.warning("red team store unreadable for run history", exc_info=True)
            return _unavailable()
        return JSONResponse([r.model_dump(mode="json") for r in runs])

    @router.get("/runs/{run_id}", response_model=RunDetail)
    async def get_run(run_id: uuid.UUID) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            found = await asyncio.to_thread(store.get_run, deps.database_url, str(run_id))
        except psycopg.Error:
            log.warning("red team store unreadable for a run", exc_info=True)
            return _unavailable()
        if found is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        return JSONResponse(RunDetail(run=found[0], executions=found[1]).model_dump(mode="json"))

    @router.get("/executions", response_model=ExecutionList)
    async def list_executions(
        limit: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        category: Category | None = None,
        outcome: Outcome | None = None,
        scenario_id: Annotated[str | None, Query(max_length=16)] = None,
        run_id: uuid.UUID | None = None,
    ) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            rows = await asyncio.to_thread(
                store.list_executions,
                deps.database_url,
                limit,
                offset,
                category,
                outcome,
                scenario_id,
                None if run_id is None else str(run_id),
            )
        except psycopg.Error:
            log.warning("red team store unreadable for executions", exc_info=True)
            return _unavailable()
        page = ExecutionList(
            executions=rows, next_offset=offset + limit if len(rows) == limit else None
        )
        return JSONResponse(page.model_dump(mode="json"))

    @router.get("/executions/{execution_id}", response_model=ExecutionRecord)
    async def get_execution(execution_id: uuid.UUID) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            row = await asyncio.to_thread(store.get_execution, deps.database_url, str(execution_id))
        except psycopg.Error:
            log.warning("red team store unreadable for an execution", exc_info=True)
            return _unavailable()
        if row is None:
            return JSONResponse({"error": "execution not found"}, status_code=404)
        return JSONResponse(row.model_dump(mode="json"))

    return router
