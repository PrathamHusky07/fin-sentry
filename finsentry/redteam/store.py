"""
Postgres persistence for Red Team runs and executions (migration 005).

Plain functions over short-lived connections, called through asyncio.to_thread by
the async runner and API, the same way the retrieval rail and the chunk fetch use
psycopg. Every execution gets its own row. Nothing here updates or deletes a
finished execution, so a rerun can never overwrite an earlier result.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finsentry.redteam.classify import Classification, Observation
from finsentry.redteam.models import Category, Outcome, Scenario
from finsentry.redteam.records import ExecutionRecord, RunRecord

# A run is bounded by the runner's own deadline. A run still marked running long
# after that belongs to a process that died, and is reclaimed instead of blocking
# every later run.
STALE_RUN_MINUTES = 15

# Migration 006: the partial unique index that allows one running run at a time.
_ONE_RUNNING_INDEX = "red_team_one_running_run"

_EXEC_COLUMNS = """
    e.execution_id::text, e.run_id::text, e.seq, e.scenario_id, e.scenario_version,
    e.category, e.target_layer, e.mode, e.expected, e.state, e.outcome, e.acting_layer,
    e.acting_check, e.expectation, e.reason, e.evidence, e.trace_ref, e.gemini_calls,
    e.cost_usd::float AS cost_usd, e.started_at, e.finished_at, e.duration_ms
"""


class RunAlreadyActiveError(Exception):
    """Another run is already in the running state. Raised by create_run when the
    database, not just this process, refuses a second running run."""


def _connect(database_url: str) -> psycopg.Connection[dict[str, Any]]:
    # psycopg's dict_row rows are typed by the driver as dict[str, Any].
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row)


def create_run(
    database_url: str,
    scenarios: Sequence[Scenario],
    allow_judge_assisted: bool,
) -> tuple[str, list[str]]:
    """Insert a running run and one queued execution per scenario, atomically.
    Returns (run_id, execution_ids in scenario order). Raises RunAlreadyActiveError when
    another process holds the one running slot."""
    run_id = str(uuid.uuid4())
    execution_ids = [str(uuid.uuid4()) for _ in scenarios]
    with _connect(database_url) as conn, conn.transaction():
        try:
            conn.execute(
                "INSERT INTO red_team_runs (run_id, status, scenario_ids, allow_judge_assisted)"
                " VALUES (%s, 'running', %s, %s)",
                (run_id, [s.id for s in scenarios], allow_judge_assisted),
            )
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name != _ONE_RUNNING_INDEX:
                raise
            raise RunAlreadyActiveError from exc
        for seq, (scenario, execution_id) in enumerate(zip(scenarios, execution_ids, strict=True)):
            conn.execute(
                "INSERT INTO red_team_executions (execution_id, run_id, seq, scenario_id,"
                " scenario_version, category, target_layer, mode, expected, state)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')",
                (
                    execution_id,
                    run_id,
                    seq,
                    scenario.id,
                    scenario.version,
                    scenario.category,
                    scenario.target_layer,
                    scenario.mode,
                    Jsonb(scenario.expected.model_dump()),
                ),
            )
    return run_id, execution_ids


def mark_running(database_url: str, execution_id: str) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            "UPDATE red_team_executions SET state = 'running', started_at = %s"
            " WHERE execution_id = %s AND state = 'queued'",
            (datetime.now(UTC), execution_id),
        )


def finish_execution(
    database_url: str,
    execution_id: str,
    outcome: Outcome,
    classification: Classification | None,
    observation: Observation | None,
    reason: str,
    duration_ms: int,
    evidence: dict[str, object] | None = None,
) -> None:
    """Record the end of an execution. classification and observation are None only
    for execution_failed, where the harness raised before any facts existed. `evidence`
    is then the only evidence there is: the runner uses it to record what a failed or
    skipped execution can still say, such as an unknown continuation. An observation's
    own evidence always wins."""
    with _connect(database_url) as conn:
        conn.execute(
            "UPDATE red_team_executions SET state = 'finished', outcome = %s,"
            " acting_layer = %s, acting_check = %s, expectation = %s, reason = %s,"
            " evidence = %s, trace_ref = %s, gemini_calls = %s, cost_usd = %s,"
            " finished_at = %s, duration_ms = %s"
            " WHERE execution_id = %s AND state <> 'finished'",
            (
                outcome,
                classification.acting_layer if classification else None,
                classification.acting_check if classification else None,
                classification.expectation if classification else "not_assessable",
                reason,
                Jsonb(observation.evidence if observation else (evidence or {})),
                observation.trace_ref if observation else None,
                observation.gemini_calls if observation else 0,
                observation.cost_usd if observation else 0,
                datetime.now(UTC),
                duration_ms,
                execution_id,
            ),
        )


def finish_run(database_url: str, run_id: str, failure_reason: str | None) -> None:
    with _connect(database_url) as conn:
        conn.execute(
            "UPDATE red_team_runs SET status = %s, finished_at = %s, failure_reason = %s"
            " WHERE run_id = %s AND status = 'running'",
            (
                "failed" if failure_reason else "completed",
                datetime.now(UTC),
                failure_reason,
                run_id,
            ),
        )


def fail_unfinished(database_url: str, run_id: str, reason: str) -> None:
    """Mark every execution of a run that never finished as execution_failed, so a run
    that stopped early leaves visible failures instead of rows stuck in queued."""
    with _connect(database_url) as conn:
        conn.execute(
            "UPDATE red_team_executions SET state = 'finished', outcome = 'execution_failed',"
            " expectation = 'not_assessable', finished_at = now(), reason = %s"
            " WHERE run_id = %s::uuid AND state <> 'finished'",
            (reason, run_id),
        )


def reclaim_stale_runs(database_url: str) -> int:
    """Fail runs a dead process left in running state, and their unfinished
    executions, so they stay visible as failed instead of looking active forever."""
    reason = "The process that started this run stopped before it finished."
    with _connect(database_url) as conn:
        stale = conn.execute(
            "UPDATE red_team_runs SET status = 'failed', finished_at = now(),"
            " failure_reason = %s"
            " WHERE status = 'running' AND created_at < now() - make_interval(mins => %s)"
            " RETURNING run_id::text AS run_id",
            (reason, STALE_RUN_MINUTES),
        ).fetchall()
    for row in stale:
        fail_unfinished(
            database_url, str(row["run_id"]), "The run ended before this execution completed."
        )
    return len(stale)


def active_run_id(database_url: str) -> str | None:
    with _connect(database_url) as conn:
        row = conn.execute(
            "SELECT run_id::text AS run_id FROM red_team_runs WHERE status = 'running'"
            " ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return None if row is None else str(row["run_id"])


def _to_execution(row: dict[str, Any]) -> ExecutionRecord:
    return ExecutionRecord.model_validate(row)


def _runs_with_counts(
    conn: psycopg.Connection[dict[str, Any]], run_rows: list[dict[str, Any]]
) -> list[RunRecord]:
    ids = [str(r["run_id"]) for r in run_rows]
    counts = conn.execute(
        "SELECT run_id::text AS run_id, state, outcome, count(*) AS n FROM red_team_executions"
        " WHERE run_id = ANY(%s::uuid[]) GROUP BY run_id, state, outcome",
        (ids,),
    ).fetchall()
    total: dict[str, int] = {}
    finished: dict[str, int] = {}
    by_outcome: dict[str, dict[str, int]] = {}
    for c in counts:
        rid, n = str(c["run_id"]), int(c["n"])
        total[rid] = total.get(rid, 0) + n
        if c["state"] == "finished":
            finished[rid] = finished.get(rid, 0) + n
        if c["outcome"] is not None:
            by_outcome.setdefault(rid, {})[str(c["outcome"])] = n
    return [
        RunRecord(
            run_id=str(r["run_id"]),
            created_at=r["created_at"],
            finished_at=r["finished_at"],
            status=r["status"],
            scenario_ids=list(r["scenario_ids"]),
            allow_judge_assisted=r["allow_judge_assisted"],
            failure_reason=r["failure_reason"],
            total=total.get(str(r["run_id"]), 0),
            finished=finished.get(str(r["run_id"]), 0),
            outcome_counts=by_outcome.get(str(r["run_id"]), {}),
        )
        for r in run_rows
    ]


def list_runs(database_url: str, limit: int) -> list[RunRecord]:
    with _connect(database_url) as conn:
        rows = conn.execute(
            "SELECT * FROM red_team_runs ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()
        return _runs_with_counts(conn, rows) if rows else []


def get_run(database_url: str, run_id: str) -> tuple[RunRecord, list[ExecutionRecord]] | None:
    with _connect(database_url) as conn:
        rows = conn.execute("SELECT * FROM red_team_runs WHERE run_id = %s", (run_id,)).fetchall()
        if not rows:
            return None
        run = _runs_with_counts(conn, rows)[0]
        executions = conn.execute(
            f"SELECT {_EXEC_COLUMNS} FROM red_team_executions e WHERE e.run_id = %s ORDER BY e.seq",
            (run_id,),
        ).fetchall()
    return run, [_to_execution(e) for e in executions]


def list_executions(
    database_url: str,
    limit: int,
    offset: int,
    category: Category | None = None,
    outcome: Outcome | None = None,
    scenario_id: str | None = None,
    run_id: str | None = None,
) -> list[ExecutionRecord]:
    conditions: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("e.category", category),
        ("e.outcome", outcome),
        ("e.scenario_id", scenario_id),
        ("e.run_id::text", run_id),
    ):
        if value is not None:
            conditions.append(f"{column} = %s")
            params.append(value)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with _connect(database_url) as conn:
        rows = conn.execute(
            f"SELECT {_EXEC_COLUMNS} FROM red_team_executions e"
            f" JOIN red_team_runs r ON r.run_id = e.run_id {where}"
            " ORDER BY r.created_at DESC, e.seq LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()
    return [_to_execution(r) for r in rows]


def get_execution(database_url: str, execution_id: str) -> ExecutionRecord | None:
    with _connect(database_url) as conn:
        row = conn.execute(
            f"SELECT {_EXEC_COLUMNS} FROM red_team_executions e WHERE e.execution_id = %s",
            (execution_id,),
        ).fetchone()
    return None if row is None else _to_execution(row)


def latest_finished_per_scenario(database_url: str) -> dict[str, ExecutionRecord]:
    """The most recent finished execution of each scenario, for the registry view."""
    with _connect(database_url) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT ON (e.scenario_id) {_EXEC_COLUMNS} FROM red_team_executions e"
            " WHERE e.state = 'finished' ORDER BY e.scenario_id, e.finished_at DESC"
        ).fetchall()
    return {r["scenario_id"]: _to_execution(r) for r in rows}
