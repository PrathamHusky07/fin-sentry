"""
The incident investigation API, mounted on the gateway under /ops/investigations so the browser
reaches it through the same-origin /ops rewrite the other console routes use.

Routes: start an investigation (behind the run password, see redteam/run_gate), list stored
sessions, read one session with its timeline and report. Only the start route can run anything.
The two reads return what is stored, plus values derived from it, and never start a run, call the
planner or write a row. Errors are short JSON with an `error` field. Nothing here returns a stack
trace, a credential or a hidden test answer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import psycopg
from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from finsentry.investigator import store
from finsentry.investigator.contracts import (
    AffectedScope,
    Confidence,
    IncidentReport,
    IncidentTrigger,
    InvestigationState,
    Subsystem,
    TimeWindow,
)
from finsentry.investigator.service import (
    InvestigationDeps,
    InvestigationRequest,
    StartRejectedError,
    start_live,
)
from finsentry.investigator.timeline import TimelineEntry
from finsentry.redteam.run_gate import HEADER, refusal, run_gate

log = logging.getLogger(__name__)

_MAX_PAGE = 50


class LeadingHypothesis(BaseModel):
    hypothesis_id: str
    subsystem: Subsystem
    confidence: Confidence
    statement: str


class InvestigationSummary(BaseModel):
    investigation_id: str
    incident_id: str
    status: store.Status
    outcome: str | None
    # live is the running platform read through the MCP tools. fixture is a known-answer case
    # world replayed through the same code, never a result on the platform.
    origin: store.Origin
    planner: str
    created_at: datetime
    finished_at: datetime | None
    trigger: IncidentTrigger
    scope: AffectedScope
    window: TimeWindow
    stopping_reason: str | None
    leading: LeadingHypothesis | None
    # None when the session stored no final state, which is not the same as none of them.
    hypotheses: int | None
    queries: int | None
    model_calls: int | None
    cost_usd: float | None
    error: str | None
    # Derived: a running session whose last event is older than the stale limit. Reading never
    # changes it. A later start reclaims it as interrupted.
    stale: bool


class InvestigationDetail(InvestigationSummary):
    heartbeat_at: datetime
    timeline: list[TimelineEntry]
    state: InvestigationState | None
    report: IncidentReport | None
    usage: store.UsageRecord | None


class InvestigationList(BaseModel):
    investigations: list[InvestigationSummary]
    next_offset: int | None


class Started(BaseModel):
    investigation: InvestigationSummary
    # False when an identical request was already running and this call started nothing.
    created: bool


def _stale(record: store.InvestigationRecord) -> bool:
    limit = timedelta(minutes=store.STALE_AFTER_MINUTES)
    return record.status == "running" and datetime.now(UTC) - record.heartbeat_at > limit


def _summary(
    record: store.InvestigationRecord, timeline: list[TimelineEntry] | None = None
) -> InvestigationSummary:
    """timeline, when the caller has it, supplies the query count of a session that stored no
    final state, since each executed query is a timeline event."""
    request = record.request
    report = record.report
    top = (
        min(report.ranked_hypotheses, key=lambda h: h.rank)
        if report and report.ranked_hypotheses
        else None
    )
    leading = (
        LeadingHypothesis(
            hypothesis_id=top.hypothesis_id,
            subsystem=top.subsystem,
            confidence=top.confidence,
            statement=top.statement,
        )
        if top and report and report.outcome == "diagnosis"
        else None
    )
    return InvestigationSummary(
        investigation_id=record.investigation_id,
        incident_id=record.incident_id,
        status=record.status,
        outcome=record.outcome,
        origin=record.origin,
        planner=record.planner,
        created_at=record.created_at,
        finished_at=record.finished_at,
        trigger=IncidentTrigger(
            kind=request["kind"],
            reference_id=request.get("reference_id"),
            description=request.get("description") or request["kind"],
        ),
        scope=AffectedScope(endpoint=request.get("endpoint"), ticker=request.get("ticker")),
        window=TimeWindow.model_validate(request["window"]),
        stopping_reason=record.stopping_reason,
        leading=leading,
        hypotheses=len(record.state.hypotheses) if record.state else None,
        queries=(
            len(record.state.executed_queries)
            if record.state
            else sum(1 for e in timeline if e.event.kind == "query")
            if timeline is not None
            else None
        ),
        model_calls=record.usage.model.calls if record.usage else None,
        cost_usd=record.usage.model.cost_usd if record.usage else None,
        error=record.error,
        stale=_stale(record),
    )


def _detail(
    record: store.InvestigationRecord, timeline: list[TimelineEntry]
) -> InvestigationDetail:
    return InvestigationDetail(
        **_summary(record, timeline).model_dump(),
        heartbeat_at=record.heartbeat_at,
        timeline=timeline,
        state=record.state,
        report=record.report,
        usage=record.usage,
    )


def _unavailable() -> JSONResponse:
    return JSONResponse({"error": "investigation store unavailable"}, status_code=503)


def build_router(get_deps: Callable[[], InvestigationDeps]) -> APIRouter:
    router = APIRouter(prefix="/ops/investigations")

    @router.post("", response_model=Started, status_code=202)
    async def start(
        request: InvestigationRequest,
        password: Annotated[str | None, Header(alias=HEADER)] = None,
    ) -> Response:
        # The same operator password and failure count as a Red Team run. The gate runs before
        # the store or the planner is touched, so a refusal creates no session, no timeline
        # event and no model call.
        decision = run_gate.check(password)
        if not decision.allowed:
            return refusal(decision)
        deps = get_deps()
        try:
            investigation_id, created = await start_live(request, deps)
            found = await asyncio.to_thread(store.get, deps.database_url, investigation_id)
        except StartRejectedError as rejected:
            body: dict[str, object] = {"error": rejected.message}
            if rejected.investigation_id:
                body["investigation_id"] = rejected.investigation_id
            return JSONResponse(body, status_code=rejected.status)
        except psycopg.Error:
            log.warning("investigation store failed while starting a session", exc_info=True)
            return _unavailable()
        if found is None:
            return _unavailable()
        body_model = Started(investigation=_summary(found[0]), created=created)
        return JSONResponse(body_model.model_dump(mode="json"), status_code=202 if created else 200)

    @router.get("", response_model=InvestigationList)
    async def list_sessions(
        limit: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
        status: store.Status | None = None,
    ) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            rows = await asyncio.to_thread(
                lambda: store.list_records(
                    deps.database_url, limit=limit + 1, offset=offset, status=status
                )
            )
        except (psycopg.Error, ValidationError):
            log.warning("investigation store unreadable for the list", exc_info=True)
            return _unavailable()
        page = InvestigationList(
            investigations=[_summary(r) for r in rows[:limit]],
            next_offset=offset + limit if len(rows) > limit else None,
        )
        return JSONResponse(page.model_dump(mode="json"))

    @router.get("/{investigation_id}", response_model=InvestigationDetail)
    async def read_session(investigation_id: str) -> Response:
        deps = get_deps()
        if not deps.database_url:
            return _unavailable()
        try:
            found = await asyncio.to_thread(store.get, deps.database_url, investigation_id)
        except psycopg.errors.InvalidTextRepresentation:
            return JSONResponse({"error": "investigation not found"}, status_code=404)
        except (psycopg.Error, ValidationError):
            log.warning("investigation store unreadable for one session", exc_info=True)
            return _unavailable()
        if found is None:
            return JSONResponse({"error": "investigation not found"}, status_code=404)
        return JSONResponse(_detail(*found).model_dump(mode="json"))

    return router
