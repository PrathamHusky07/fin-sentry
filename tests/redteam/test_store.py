"""Persistence against the real test database: distinct executions, honest states, stale reclaim."""

from __future__ import annotations

import psycopg
import pytest

from finsentry.redteam import store
from finsentry.redteam.classify import Classification, Observation
from finsentry.redteam.registry import get_scenario
from tests.conftest import TEST_DATABASE_URL


def _scenarios(*ids: str):  # type: ignore[no-untyped-def]
    found = [get_scenario(i) for i in ids]
    assert all(s is not None for s in found)
    return [s for s in found if s is not None]


def _finish(
    execution_id: str, outcome: str = "caught", layer: str | None = "prompt-guard-2"
) -> None:
    obs = Observation(summary="s", evidence={"gateway_status": 403}, trace_ref="trace-1")
    cls = Classification(outcome, "met", "Blocked.", acting_layer=layer)  # type: ignore[arg-type]
    store.finish_execution(TEST_DATABASE_URL, execution_id, outcome, cls, obs, cls.reason, 42)  # type: ignore[arg-type]


def test_create_run_inserts_queued_executions_with_the_expectation_copied() -> None:
    run_id, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001", "OUT-001"), False)
    detail = store.get_run(TEST_DATABASE_URL, run_id)
    assert detail is not None
    run, executions = detail
    assert run.status == "running"
    assert (run.total, run.finished) == (2, 0)
    assert [e.execution_id for e in executions] == ids
    assert all(e.state == "queued" and e.outcome is None for e in executions)
    assert executions[0].expected.layer == "prompt-guard-2"
    assert executions[0].scenario_version == 1


def test_a_rerun_of_the_same_scenario_is_a_new_execution_record() -> None:
    first_run, first_ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    store.finish_run(TEST_DATABASE_URL, first_run, None)  # only one run may be running
    second_run, second_ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    _finish(first_ids[0])
    _finish(second_ids[0], outcome="missed", layer=None)
    assert first_run != second_run and first_ids != second_ids
    rows = store.list_executions(TEST_DATABASE_URL, 50, 0, scenario_id="DI-001")
    assert len(rows) == 2
    assert {r.outcome for r in rows} == {"caught", "missed"}


def test_finishing_an_execution_persists_the_observed_outcome_apart_from_expected() -> None:
    _, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    store.mark_running(TEST_DATABASE_URL, ids[0])
    _finish(ids[0])
    row = store.get_execution(TEST_DATABASE_URL, ids[0])
    assert row is not None
    assert row.state == "finished" and row.outcome == "caught"
    assert row.acting_layer == "prompt-guard-2"
    assert row.expected.outcome == "caught"
    assert row.trace_ref == "trace-1"
    assert row.duration_ms == 42
    assert row.started_at is not None and row.finished_at is not None


def test_a_finished_execution_is_never_overwritten() -> None:
    _, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    _finish(ids[0], outcome="caught")
    _finish(ids[0], outcome="missed", layer=None)
    row = store.get_execution(TEST_DATABASE_URL, ids[0])
    assert row is not None and row.outcome == "caught"


def test_execution_failed_is_stored_without_an_observation() -> None:
    _, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    store.finish_execution(
        TEST_DATABASE_URL, ids[0], "execution_failed", None, None, "The harness raised.", 5
    )
    row = store.get_execution(TEST_DATABASE_URL, ids[0])
    assert row is not None
    assert (row.outcome, row.expectation, row.acting_layer) == (
        "execution_failed",
        "not_assessable",
        None,
    )


def test_the_database_rejects_a_finished_row_without_an_outcome() -> None:
    _, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE red_team_executions SET state = 'finished' WHERE execution_id = %s",
                (ids[0],),
            )


def test_run_counts_are_derived_from_finished_rows() -> None:
    run_id, ids = store.create_run(
        TEST_DATABASE_URL, _scenarios("DI-001", "OUT-001", "GAP-001"), False
    )
    _finish(ids[0])
    _finish(ids[1])
    _finish(ids[2], outcome="missed", layer=None)
    store.finish_run(TEST_DATABASE_URL, run_id, None)
    run = store.list_runs(TEST_DATABASE_URL, 10)[0]
    assert run.status == "completed"
    assert (run.total, run.finished) == (3, 3)
    assert run.outcome_counts == {"caught": 2, "missed": 1}


def test_list_executions_filters_by_category_outcome_and_run() -> None:
    run_id, ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001", "OUT-001"), False)
    _finish(ids[0])
    _finish(ids[1], outcome="missed", layer=None)
    by_category = store.list_executions(TEST_DATABASE_URL, 50, 0, category="output_schema")
    assert [e.scenario_id for e in by_category] == ["OUT-001"]
    by_outcome = store.list_executions(TEST_DATABASE_URL, 50, 0, outcome="caught")
    assert [e.scenario_id for e in by_outcome] == ["DI-001"]
    by_run = store.list_executions(TEST_DATABASE_URL, 50, 0, run_id=run_id)
    assert len(by_run) == 2
    assert store.list_executions(TEST_DATABASE_URL, 50, 0, run_id="not-a-run") == []


def test_a_failed_run_keeps_its_reason_and_stays_listed() -> None:
    run_id, _ = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    store.finish_run(TEST_DATABASE_URL, run_id, "The run deadline passed.")
    run = store.list_runs(TEST_DATABASE_URL, 10)[0]
    assert (run.status, run.failure_reason) == ("failed", "The run deadline passed.")


def test_only_a_stale_running_run_is_reclaimed_and_its_unfinished_executions_fail() -> None:
    stale_run, stale_ids = store.create_run(
        TEST_DATABASE_URL, _scenarios("DI-001", "OUT-001"), False
    )
    _finish(stale_ids[0])
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE red_team_runs SET created_at = now() - interval '1 hour' WHERE run_id = %s",
            (stale_run,),
        )
    assert store.reclaim_stale_runs(TEST_DATABASE_URL) == 1
    detail = store.get_run(TEST_DATABASE_URL, stale_run)
    assert detail is not None
    run, executions = detail
    assert run.status == "failed" and run.failure_reason is not None
    assert [e.outcome for e in executions] == ["caught", "execution_failed"]
    # The reclaim freed the one running slot, and it leaves a valid active run alone.
    assert store.active_run_id(TEST_DATABASE_URL) is None
    fresh_run, _ = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
    assert store.reclaim_stale_runs(TEST_DATABASE_URL) == 0
    assert store.active_run_id(TEST_DATABASE_URL) == fresh_run


def test_get_unknown_ids_return_none() -> None:
    assert store.get_run(TEST_DATABASE_URL, "00000000-0000-0000-0000-000000000000") is None
    assert store.get_execution(TEST_DATABASE_URL, "00000000-0000-0000-0000-000000000000") is None


def test_migration_006_keeps_the_newest_running_run_and_closes_the_rest() -> None:
    from finsentry.db.migrate import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "006_red_team_single_active_run.sql").read_text()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP INDEX red_team_one_running_run")
        try:
            old_run, old_ids = store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
            conn.execute(
                "UPDATE red_team_runs SET created_at = now() - interval '5 minutes'"
                " WHERE run_id = %s",
                (old_run,),
            )
            newest_run, _ = store.create_run(TEST_DATABASE_URL, _scenarios("HZ-001"), False)
            conn.execute(sql)
        finally:
            conn.execute(sql)  # the index must exist again whatever happened above
    assert store.active_run_id(TEST_DATABASE_URL) == newest_run
    old = store.get_run(TEST_DATABASE_URL, old_run)
    assert old is not None
    assert old[0].status == "failed" and "migration 006" in (old[0].failure_reason or "")
    assert [e.outcome for e in old[1]] == ["execution_failed"]
    with pytest.raises(store.RunAlreadyActiveError):
        store.create_run(TEST_DATABASE_URL, _scenarios("DI-001"), False)
