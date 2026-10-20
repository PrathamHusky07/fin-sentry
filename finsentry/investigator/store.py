"""
Postgres persistence for investigation sessions (migration 007).

Plain functions over short-lived connections, called through asyncio.to_thread, the same way the
Red Team store is. A session is one row plus its timeline events. Every update to a row is
guarded by status = 'running', so a late writer can never replace a state that already ended: a
session that was reclaimed as interrupted stays interrupted even if its task finishes later, and
a completed report is never overwritten. Reading never writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finsentry.investigator.contracts import (
    Budgets,
    BudgetUsage,
    IncidentReport,
    InvestigationState,
)
from finsentry.investigator.timeline import TimelineEntry

# A session still marked running after this long without an event belongs to a process that
# stopped. Its own deadline is 120 seconds, so this leaves room for a slow model call.
STALE_AFTER_MINUTES = 5

Status = Literal["running", "completed", "failed", "interrupted"]
Origin = Literal["live", "fixture"]

_ONE_RUNNING_INDEX = "investigations_one_running"

STALE_ERROR = (
    "The process running this investigation stopped before it finished. It was not resumed. "
    "Start a new investigation to look again."
)


class ActiveInvestigationError(Exception):
    """Another investigation is already running. Raised when the database, not just this
    process, refuses a second running session."""


class ModelUsage(BaseModel):
    """What the planner spent. cost_usd is counted from the provider's usage metadata at the
    platform's published rates (an estimate, not a billing figure). A call that failed after
    its request was sent is charged at a pessimistic estimate and counted in unmetered_calls."""

    model_config = ConfigDict(extra="forbid")

    planner: str
    calls: int = 0
    unmetered_calls: int = 0
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    thought_tokens: int = 0
    cost_usd: float = 0.0
    # One entry per planner call: which round, how long it took, and how it ended.
    call_log: list[dict[str, object]] = Field(default_factory=list)


class UsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budgets: Budgets
    used: BudgetUsage
    model: ModelUsage


class InvestigationRecord(BaseModel):
    """One stored session as read back. state and report are None until the session ends, and
    a failed one keeps the last good state."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    incident_id: str
    created_at: datetime
    finished_at: datetime | None
    heartbeat_at: datetime
    status: Status
    origin: Origin
    planner: str
    agent_version: str
    request: dict[str, Any]
    outcome: Literal["diagnosis", "abstention"] | None
    stopping_reason: str | None
    state: InvestigationState | None
    report: IncidentReport | None
    usage: UsageRecord | None
    error: str | None


def _connect(database_url: str) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row)


_COLUMNS = (
    "investigation_id::text, incident_id, created_at, finished_at, heartbeat_at, status, origin,"
    " planner, agent_version, request, outcome, stopping_reason, state, report, usage, error"
)


def _record(row: dict[str, Any]) -> InvestigationRecord:
    return InvestigationRecord.model_validate(row)


def create(
    database_url: str,
    *,
    investigation_id: str,
    incident_id: str,
    origin: Origin,
    planner: str,
    agent_version: str,
    request: dict[str, Any],
    request_key: str,
) -> None:
    """Insert a running session. Raises ActiveInvestigationError when another one holds the
    single running slot."""
    try:
        with _connect(database_url) as conn:
            conn.execute(
                "INSERT INTO investigations (investigation_id, incident_id, status, origin,"
                " planner, agent_version, request, request_key)"
                " VALUES (%s, %s, 'running', %s, %s, %s, %s, %s)",
                (
                    investigation_id,
                    incident_id,
                    origin,
                    planner,
                    agent_version,
                    Jsonb(request),
                    request_key,
                ),
            )
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != _ONE_RUNNING_INDEX:
            raise
        raise ActiveInvestigationError from exc


def active(database_url: str) -> tuple[str, str] | None:
    """The id and request key of the running session, or None."""
    with _connect(database_url) as conn:
        row = conn.execute(
            "SELECT investigation_id::text AS id, request_key FROM investigations"
            " WHERE status = 'running'"
        ).fetchone()
    return (row["id"], row["request_key"]) if row else None


def append_event(database_url: str, investigation_id: str, entry: TimelineEntry) -> None:
    """Store one timeline event and show the session is alive. Idempotent on (id, seq)."""
    with _connect(database_url) as conn, conn.transaction():
        conn.execute(
            "INSERT INTO investigation_events (investigation_id, seq, at, elapsed_s, kind, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (
                investigation_id,
                entry.seq,
                entry.at,
                entry.elapsed_s,
                entry.event.kind,
                Jsonb(entry.event.model_dump(mode="json")),
            ),
        )
        conn.execute(
            "UPDATE investigations SET heartbeat_at = %s"
            " WHERE investigation_id = %s AND status = 'running'",
            (datetime.now(UTC), investigation_id),
        )


def complete(
    database_url: str,
    investigation_id: str,
    state: InvestigationState,
    report: IncidentReport,
    usage: UsageRecord,
) -> bool:
    """Store the finished session. False when it was no longer running (it was reclaimed)."""
    with _connect(database_url) as conn:
        cur = conn.execute(
            "UPDATE investigations SET status = 'completed', finished_at = %s, outcome = %s,"
            " stopping_reason = %s, state = %s, report = %s, usage = %s"
            " WHERE investigation_id = %s AND status = 'running'",
            (
                datetime.now(UTC),
                report.outcome,
                report.stopping_reason,
                Jsonb(state.model_dump(mode="json")),
                Jsonb(report.model_dump(mode="json")),
                Jsonb(usage.model_dump(mode="json")),
                investigation_id,
            ),
        )
        return cur.rowcount == 1


def end_without_report(
    database_url: str,
    investigation_id: str,
    status: Literal["failed", "interrupted"],
    error: str,
    state: InvestigationState | None,
    usage: UsageRecord | None,
) -> bool:
    """Store a session that ended without a report, keeping the last good state and the spend."""
    with _connect(database_url) as conn:
        cur = conn.execute(
            "UPDATE investigations SET status = %s, finished_at = %s, error = %s, state = %s,"
            " usage = %s WHERE investigation_id = %s AND status = 'running'",
            (
                status,
                datetime.now(UTC),
                error[:500],
                Jsonb(state.model_dump(mode="json")) if state else None,
                Jsonb(usage.model_dump(mode="json")) if usage else None,
                investigation_id,
            ),
        )
        return cur.rowcount == 1


def reclaim_stale(database_url: str, minutes: float = STALE_AFTER_MINUTES) -> int:
    """Mark sessions whose process stopped as interrupted, so they stop blocking new ones and
    read as what they are. Only a heartbeat older than `minutes` qualifies."""
    with _connect(database_url) as conn:
        cur = conn.execute(
            "UPDATE investigations SET status = 'interrupted', finished_at = now(), error = %s"
            " WHERE status = 'running' AND heartbeat_at < now() - (%s * INTERVAL '1 minute')",
            (STALE_ERROR, minutes),
        )
        return cur.rowcount


def get(
    database_url: str, investigation_id: str
) -> tuple[InvestigationRecord, list[TimelineEntry]] | None:
    with _connect(database_url) as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM investigations WHERE investigation_id = %s",
            (investigation_id,),
        ).fetchone()
        if row is None:
            return None
        events = conn.execute(
            "SELECT seq, at, elapsed_s, payload FROM investigation_events"
            " WHERE investigation_id = %s ORDER BY seq",
            (investigation_id,),
        ).fetchall()
    entries = [
        TimelineEntry.model_validate(
            {"seq": e["seq"], "at": e["at"], "elapsed_s": e["elapsed_s"], "event": e["payload"]}
        )
        for e in events
    ]
    return _record(row), entries


def list_records(
    database_url: str, *, limit: int, offset: int, status: Status | None = None
) -> list[InvestigationRecord]:
    where, params = ("WHERE status = %s", [status]) if status else ("", [])
    with _connect(database_url) as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM investigations {where}"
            " ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()
    return [_record(r) for r in rows]


def delete_fixtures(database_url: str) -> int:
    """Remove fixture sessions only, so a reseed replaces them. Live sessions are never touched."""
    with _connect(database_url) as conn, conn.transaction():
        conn.execute(
            "DELETE FROM investigation_events WHERE investigation_id IN"
            " (SELECT investigation_id FROM investigations WHERE origin = 'fixture')"
        )
        cur = conn.execute("DELETE FROM investigations WHERE origin = 'fixture'")
        return cur.rowcount
