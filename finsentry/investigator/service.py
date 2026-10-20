"""
Runs an investigation as a durable session.

start_live validates a request, refuses it when it cannot run, creates the session row and runs
the bounded investigator in the background against the live platform through the nine read-only
MCP tools and the Gemini planner. run_investigation is the part both a live run and a fixture
run share: it drives one investigator, stores every timeline event as it happens and ends the
session in exactly one state. The database allows one running session at a time, so a duplicate
or concurrent start is answered from the row that already holds the slot.

Nothing here resumes a session. One that was cut off ends as interrupted and a new
investigation is started to look again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finsentry.investigator import store
from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import (
    AffectedScope,
    IncidentTrigger,
    InvestigationState,
    TimeWindow,
    TriggerKind,
)
from finsentry.investigator.loop import (
    BoundedInvestigator,
    Clock,
    InvestigationFailedError,
    Investigator,
    start_investigation,
)
from finsentry.investigator.planning import Plan, Planner, PlanningError
from finsentry.investigator.timeline import EventRecorder, TimelineEntry
from finsentry.investigator.tool_args import validate_tool_args
from finsentry.investigator.tool_contract import McpReadTools

log = logging.getLogger(__name__)

ToolSession = Callable[[], AbstractAsyncContextManager[McpReadTools]]


class InvestigationRequest(BaseModel):
    """What a person asks for. The window ends when the request is accepted and runs back
    window_minutes. A single_trace or red_team_miss trigger names the record it is about."""

    model_config = ConfigDict(extra="forbid")

    kind: TriggerKind
    reference_id: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, min_length=1, max_length=100)
    ticker: str | None = Field(default=None, min_length=1, max_length=12)
    window_minutes: int = Field(default=60, ge=1, le=1440)

    @model_validator(mode="after")
    def _reference_is_valid_for_the_trigger(self) -> InvestigationRequest:
        by_kind = {
            "single_trace": ("get_trace_detail", "app_trace_id"),
            "red_team_miss": ("get_red_team_execution", "execution_id"),
        }
        if self.kind not in by_kind:
            if self.reference_id is not None:
                raise ValueError(f"a {self.kind} trigger takes no reference_id")
            return self
        if self.reference_id is None:
            raise ValueError(f"a {self.kind} trigger needs a reference_id")
        tool, arg = by_kind[self.kind]
        problems = validate_tool_args(tool, {arg: self.reference_id})
        if problems:
            raise ValueError(f"reference_id is not valid for {self.kind}: {'; '.join(problems)}")
        return self

    def key(self) -> str:
        """Identifies the ask, so an identical one made while it is running is the same ask."""
        fields = self.model_dump(exclude={"description"})
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]

    def trigger(self) -> IncidentTrigger:
        return IncidentTrigger(
            kind=self.kind,
            reference_id=self.reference_id,
            description=self.description or f"{self.kind.replace('_', ' ')} investigation",
        )

    def scope(self) -> AffectedScope:
        return AffectedScope(endpoint=self.endpoint, ticker=self.ticker)

    def window(self, end: datetime) -> TimeWindow:
        return TimeWindow(start=end - timedelta(minutes=self.window_minutes), end=end)


class StartRejectedError(Exception):
    """The request cannot start a session. `status` is the HTTP status the API answers."""

    def __init__(self, status: int, message: str, investigation_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.investigation_id = investigation_id


@dataclass
class InvestigationDeps:
    database_url: str
    # None when no model is configured here, which refuses a live start before any row exists.
    planner_factory: Callable[[], Planner] | None
    tool_session: ToolSession
    clock: Clock = time.monotonic
    tasks: set[asyncio.Task[None]] = field(default_factory=set)


class RecordingPlanner:
    """Wraps a planner and keeps one entry per call: the round, how long it took and how it
    ended, with the error class when it failed."""

    def __init__(self, inner: Planner) -> None:
        self.inner = inner
        self.name = inner.name
        self.log: list[dict[str, object]] = []

    @property
    def cost_usd(self) -> float:
        return self.inner.cost_usd

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        started, before = time.monotonic(), self.inner.cost_usd
        entry: dict[str, object] = {"round": round_no, "outcome": "ok", "error_class": None}
        try:
            return await self.inner.plan(digest, round_no=round_no)
        except BaseException as exc:
            entry.update(outcome="failed", error_class=type(exc).__name__)
            raise
        finally:
            entry["elapsed_s"] = round(time.monotonic() - started, 2)
            entry["cost_usd"] = round(self.inner.cost_usd - before, 6)
            self.log.append(entry)

    def usage(self) -> store.ModelUsage:
        inner: Any = self.inner
        tokens = getattr(inner, "tokens", {})
        return store.ModelUsage(
            planner=self.name,
            calls=getattr(inner, "calls", 0),
            unmetered_calls=getattr(inner, "unmetered_calls", 0),
            prompt_tokens=tokens.get("prompt", 0),
            candidates_tokens=tokens.get("candidates", 0),
            thought_tokens=tokens.get("thoughts", 0),
            cost_usd=round(self.inner.cost_usd, 6),
            call_log=self.log,
        )


def _usage(state: InvestigationState, planner: RecordingPlanner) -> store.UsageRecord:
    return store.UsageRecord(budgets=state.budgets, used=state.usage, model=planner.usage())


def request_record(request: InvestigationRequest, window: TimeWindow) -> dict[str, Any]:
    return {
        **request.model_dump(mode="json"),
        "window": window.model_dump(mode="json"),
    }


async def run_investigation(
    database_url: str,
    investigation_id: str,
    state: InvestigationState,
    tools: McpReadTools,
    planner: Planner,
    *,
    clock: Clock = time.monotonic,
    investigator: Callable[[RecordingPlanner, EventRecorder], Investigator] | None = None,
) -> None:
    """Drive one investigator over a session that is already stored as running, and end the
    session in one state: completed (a diagnosis or an abstention), failed, or interrupted."""

    async def sink(entry: TimelineEntry) -> None:
        await asyncio.to_thread(store.append_event, database_url, investigation_id, entry)

    recorder = EventRecorder(sink)
    recording = RecordingPlanner(planner)
    run = (investigator or _default_investigator)(recording, recorder)
    try:
        result = await run.investigate(state, ReadOnlyAdapter(tools), clock)
    except asyncio.CancelledError:
        await recorder.flush()
        await asyncio.to_thread(
            store.end_without_report,
            database_url,
            investigation_id,
            "interrupted",
            "The gateway stopped while this investigation was running. It was not resumed. "
            "Start a new investigation to look again.",
            None,
            None,
        )
        raise
    except InvestigationFailedError as exc:
        await recorder.flush()
        kept = exc.state
        await asyncio.to_thread(
            store.end_without_report,
            database_url,
            investigation_id,
            "failed",
            str(exc),
            kept,
            _usage(kept, recording),
        )
        return
    except Exception as exc:
        log.exception("investigation %s failed", investigation_id)
        await recorder.flush()
        await asyncio.to_thread(
            store.end_without_report,
            database_url,
            investigation_id,
            "failed",
            f"{type(exc).__name__}: {exc}",
            None,
            None,
        )
        return
    await recorder.flush()
    stored = await asyncio.to_thread(
        store.complete,
        database_url,
        investigation_id,
        result.state,
        result.report,
        _usage(result.state, recording),
    )
    if not stored:
        log.warning("investigation %s finished after it was already ended", investigation_id)


def _default_investigator(planner: RecordingPlanner, recorder: EventRecorder) -> Investigator:
    return BoundedInvestigator(planner, recorder=recorder)


async def _run_live(
    deps: InvestigationDeps,
    investigation_id: str,
    state: InvestigationState,
    planner: Planner,
) -> None:
    try:
        async with deps.tool_session() as tools:
            await run_investigation(
                deps.database_url, investigation_id, state, tools, planner, clock=deps.clock
            )
    except asyncio.CancelledError:
        await asyncio.to_thread(
            store.end_without_report,
            deps.database_url,
            investigation_id,
            "interrupted",
            "The gateway stopped while this investigation was starting. It was not resumed.",
            None,
            None,
        )
        raise
    except Exception as exc:
        log.exception("investigation %s could not use the tool server", investigation_id)
        await asyncio.to_thread(
            store.end_without_report,
            deps.database_url,
            investigation_id,
            "failed",
            f"The read-only tool server could not be used: {type(exc).__name__}",
            None,
            None,
        )


async def start_live(request: InvestigationRequest, deps: InvestigationDeps) -> tuple[str, bool]:
    """Accept a request and start it in the background. Returns the session id and whether this
    call created it. An identical request made while it runs returns the running session and
    creates nothing, so a double click or a retry never starts a second one."""
    if not deps.database_url:
        raise StartRejectedError(503, "The investigation store is not configured.")
    if deps.planner_factory is None:
        raise StartRejectedError(503, "No model is configured here, so no investigation can run.")
    await asyncio.to_thread(store.reclaim_stale, deps.database_url)
    running = await asyncio.to_thread(store.active, deps.database_url)
    if running is not None:
        if running[1] == request.key():
            return running[0], False
        raise StartRejectedError(409, "An investigation is already running.", running[0])
    try:
        planner = deps.planner_factory()
    except PlanningError as exc:
        raise StartRejectedError(503, f"No model is configured here: {exc}") from exc
    window = request.window(datetime.now(UTC))
    investigation_id = str(uuid.uuid4())
    incident_id = f"inc-{investigation_id[:8]}"
    try:
        await asyncio.to_thread(
            lambda: store.create(
                deps.database_url,
                investigation_id=investigation_id,
                incident_id=incident_id,
                origin="live",
                planner=planner.name,
                agent_version=f"bounded-investigator-1+{planner.name}",
                request=request_record(request, window),
                request_key=request.key(),
            )
        )
    except store.ActiveInvestigationError:
        winner = await asyncio.to_thread(store.active, deps.database_url)
        if winner is not None and winner[1] == request.key():
            return winner[0], False
        raise StartRejectedError(
            409, "An investigation is already running.", winner[0] if winner else None
        ) from None
    state = start_investigation(incident_id, request.trigger(), window, scope=request.scope())
    task = asyncio.create_task(_run_live(deps, investigation_id, state, planner))
    deps.tasks.add(task)
    task.add_done_callback(deps.tasks.discard)
    return investigation_id, True


async def stop_active(deps: InvestigationDeps) -> None:
    """Cancel this process's running sessions at shutdown. Each ends as interrupted."""
    tasks = list(deps.tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
