"""
list_red_team_executions and get_red_team_execution: read-only views of the Red Team
Console's stored results (Postgres, migration 005).

These read finished and in-flight rows only. Starting a run from an agent is not exposed.
They reuse the store functions and result models behind /ops/redteam, so the shape is the
persisted ExecutionRecord. Its evidence holds measured facts, never raw model output.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from pydantic import BaseModel

from finsentry.mcp._util import validate_limit
from finsentry.redteam import store
from finsentry.redteam.models import Category, Outcome
from finsentry.redteam.records import ExecutionList, ExecutionRecord

MAX_EXECUTION_PAGE = 100


class RedTeamExecutionResult(BaseModel):
    found: bool
    execution: ExecutionRecord | None


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL is not configured, so the red team store cannot be read")
    return url


def _check_uuid(name: str, value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"{name} must be a UUID") from None


async def list_red_team_executions(
    limit: int = 20,
    offset: int = 0,
    category: Category | None = None,
    outcome: Outcome | None = None,
    scenario_id: str | None = None,
    run_id: str | None = None,
) -> ExecutionList:
    """List stored Red Team executions, newest run first, in scenario order within a run.

    Each execution is one scenario fired once. outcome is one of caught, missed,
    evaluator_unavailable, execution_failed or inconclusive, and is null while the
    execution is queued or running. expected is the scenario's hypothesis and outcome is
    what was observed, so compare them through expectation (met, not_met or
    not_assessable). trace_ref, when present, is an app_trace_id for get_trace_detail.
    Results are capped at 100 per page. Use next_offset to continue.
    """
    validate_limit(limit, MAX_EXECUTION_PAGE)
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if scenario_id is not None and len(scenario_id) > 16:
        raise ValueError("scenario_id must be at most 16 characters")
    rows = await asyncio.to_thread(
        store.list_executions,
        _database_url(),
        limit,
        offset,
        category,
        outcome,
        scenario_id,
        None if run_id is None else _check_uuid("run_id", run_id),
    )
    return ExecutionList(
        executions=rows, next_offset=offset + limit if len(rows) == limit else None
    )


async def get_red_team_execution(execution_id: str) -> RedTeamExecutionResult:
    """Return one stored Red Team execution with its full recorded evidence, its
    classification reason, the Gemini calls and cost it recorded, and the trace it
    references. found is False when no execution has that id."""
    row = await asyncio.to_thread(
        store.get_execution, _database_url(), _check_uuid("execution_id", execution_id)
    )
    return RedTeamExecutionResult(found=row is not None, execution=row)
