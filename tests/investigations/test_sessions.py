"""Investigation sessions are durable: stored once, reopened as recorded, and never rerun.

These run against the test Postgres through the same store, recorder and service a live run
uses. A fixture session is a case world replayed by the planner double, so none of them calls a
model.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from finsentry.investigator import store
from finsentry.investigator.citations import validate_report
from finsentry.investigator.evaluation import seed
from finsentry.investigator.service import (
    InvestigationRequest,
    StartRejectedError,
    start_live,
    stop_active,
)
from tests.conftest import TEST_DATABASE_URL as URL
from tests.investigations.helpers import (
    CASES,
    ForbiddenPlanner,
    GatedPlanner,
    deps_for,
    settle,
    sql,
)


def read(investigation_id: str) -> tuple[store.InvestigationRecord, list]:  # type: ignore[type-arg]
    found = store.get(URL, investigation_id)
    assert found is not None
    return found


# What a finished session stores.


async def test_a_diagnosis_is_stored_whole_and_reopens_as_recorded() -> None:
    investigation_id = await seed.seed_case(URL, seed.COMPLETED_DIAGNOSIS)
    record, timeline = read(investigation_id)
    assert (record.status, record.outcome, record.origin) == ("completed", "diagnosis", "fixture")
    assert record.report is not None and record.state is not None and record.usage is not None
    assert validate_report(record.report, record.state).valid
    assert record.report.ranked_hypotheses[0].subsystem == "judges"
    assert record.state.executed_queries and record.state.hypotheses
    assert record.stopping_reason == record.report.stopping_reason == "sufficient_evidence"
    assert record.error is None and record.finished_at is not None
    kinds = [e.event.kind for e in timeline]
    assert kinds[0] == "query" and kinds[-1] == "stopped"
    assert {"plan", "assessment"} <= set(kinds)
    assert [e.seq for e in timeline] == list(range(1, len(timeline) + 1))


async def test_reopening_after_a_restart_returns_the_same_record_and_runs_nothing() -> None:
    """A restart drops every in-memory object. The stored session is read back whole, and no
    planner is asked for anything."""
    investigation_id = await seed.seed_case(URL, seed.COMPLETED_DIAGNOSIS)
    first, first_timeline = read(investigation_id)
    before = sql("SELECT count(*) FROM investigations")[0][0]

    del first  # nothing in memory survives a restart
    second, second_timeline = read(investigation_id)
    deps = deps_for(seed.COMPLETED_DIAGNOSIS, ForbiddenPlanner())  # a fresh process's deps
    assert deps.tasks == set()

    assert second.report is not None and second.report.outcome == "diagnosis"
    assert [e.seq for e in second_timeline] == [e.seq for e in first_timeline]
    assert sql("SELECT count(*) FROM investigations")[0][0] == before
    assert len(store.list_records(URL, limit=10, offset=0)) == 1


async def test_an_abstention_is_a_completed_outcome_and_not_an_error() -> None:
    investigation_id = await seed.seed_case(URL, seed.JUSTIFIED_ABSTENTION)
    record, timeline = read(investigation_id)
    assert (record.status, record.outcome) == ("completed", "abstention")
    assert record.error is None and record.report is not None
    assert record.report.abstention_statement is not None
    assert record.report.proposed_verification.executed is False
    stop = timeline[-1].event
    assert stop.kind == "stopped" and stop.outcome == "abstention" and stop.why


async def test_an_unavailable_source_is_kept_apart_from_an_empty_result() -> None:
    investigation_id = await seed.seed_case(URL, seed.UNAVAILABLE_SOURCE)
    record, timeline = read(investigation_id)
    assert (record.status, record.outcome) == ("completed", "abstention")
    assert record.stopping_reason == "critical_evidence_unavailable"
    assert record.report is not None
    assert "get_failing_traces" in record.report.tool_unavailable
    assert record.report.empty_results == []
    queries = [e.event for e in timeline if e.event.kind == "query"]
    assert queries and all(q.status == "unavailable" for q in queries)  # type: ignore[union-attr]
    assert record.usage is not None and record.usage.model.calls == 0


async def test_a_failed_investigation_keeps_its_last_state_and_says_why() -> None:
    investigation_id = await seed.seed_case(URL, seed.FAILED_RUN, crash=True)
    record, timeline = read(investigation_id)
    assert record.status == "failed" and record.outcome is None and record.report is None
    assert record.error is not None and "FixtureFault" in record.error
    assert record.state is not None and len(record.state.executed_queries) == 1
    assert record.usage is not None and record.usage.used.tool_calls == 1
    assert [e.event.kind for e in timeline] == ["query"]
    assert record.finished_at is not None


async def test_an_interrupted_investigation_is_explicit_and_not_resumable() -> None:
    investigation_id = await seed.seed_interrupted(URL, seed.INTERRUPTED_RUN)
    record, timeline = read(investigation_id)
    assert record.status == "interrupted" and record.report is None
    assert record.error == store.STALE_ERROR and "not resumed" in record.error
    assert timeline, "the events stored before it stopped are kept"
    assert sql("SELECT count(*) FROM investigations WHERE status = 'running'")[0][0] == 0


async def test_a_fixture_session_is_labelled_as_a_fixture_with_the_double_as_planner() -> None:
    investigation_id = await seed.seed_case(URL, seed.COMPLETED_DIAGNOSIS)
    record, _ = read(investigation_id)
    assert record.origin == "fixture" and record.planner == "planner-double"
    assert record.usage is not None and record.usage.model.cost_usd == 0


# One running session at a time, and no duplicate starts.


def test_the_database_allows_one_running_session() -> None:
    kwargs = dict(
        incident_id="inc-x",
        origin="live",
        planner="p",
        agent_version="v",
        request={},
        request_key="k",
    )
    store.create(URL, investigation_id="00000000-0000-0000-0000-000000000001", **kwargs)  # type: ignore[arg-type]
    with pytest.raises(store.ActiveInvestigationError):
        store.create(URL, investigation_id="00000000-0000-0000-0000-000000000002", **kwargs)  # type: ignore[arg-type]
    assert sql("SELECT count(*) FROM investigations")[0][0] == 1


async def test_an_identical_concurrent_start_returns_the_running_session() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    request = InvestigationRequest(kind="drift_degradation")
    results = await asyncio.gather(*(start_live(request, deps) for _ in range(5)))
    ids = {r[0] for r in results}
    assert len(ids) == 1 and sorted(r[1] for r in results) == [False] * 4 + [True]
    assert sql("SELECT count(*) FROM investigations")[0][0] == 1
    planner.release.set()
    await settle(deps)
    record, _ = read(ids.pop())
    assert record.status == "completed" and record.origin == "live"


async def test_a_different_request_while_one_runs_is_refused_with_the_running_id() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    running, _ = await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    with pytest.raises(StartRejectedError) as refused:
        await start_live(InvestigationRequest(kind="error_kind_surge"), deps)
    assert refused.value.status == 409 and refused.value.investigation_id == running
    planner.release.set()
    await settle(deps)


async def test_an_identical_request_after_it_finished_is_a_new_session() -> None:
    planner = GatedPlanner()
    planner.release.set()
    deps = deps_for("sparse-signal", planner)
    request = InvestigationRequest(kind="drift_degradation")
    first, created_first = await start_live(request, deps)
    await settle(deps)
    second, created_second = await start_live(request, deps)
    await settle(deps)
    assert first != second and created_first and created_second
    assert sql("SELECT count(*) FROM investigations")[0][0] == 2


# Stale and concurrent updates.


def _running(investigation_id: str) -> None:
    store.create(
        URL,
        investigation_id=investigation_id,
        incident_id="inc-x",
        origin="live",
        planner="p",
        agent_version="v",
        request={},
        request_key="k",
    )


def test_a_session_with_a_stale_heartbeat_is_reclaimed_as_interrupted() -> None:
    stale, fresh = "00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b"
    _running(stale)
    sql(
        "UPDATE investigations SET heartbeat_at = %s WHERE investigation_id = %s",
        datetime.now(UTC) - timedelta(minutes=store.STALE_AFTER_MINUTES + 1),
        stale,
    )
    assert store.reclaim_stale(URL) == 1
    assert read(stale)[0].status == "interrupted"
    _running(fresh)
    assert store.reclaim_stale(URL) == 0, "a session with a fresh heartbeat is left alone"
    assert read(fresh)[0].status == "running"


async def test_a_late_writer_cannot_replace_a_session_that_already_ended() -> None:
    investigation_id = await seed.seed_case(URL, seed.COMPLETED_DIAGNOSIS)
    record, _ = read(investigation_id)
    assert record.report is not None and record.state is not None and record.usage is not None
    assert store.complete(URL, investigation_id, record.state, record.report, record.usage) is False
    assert store.end_without_report(URL, investigation_id, "failed", "late", None, None) is False
    after, _ = read(investigation_id)
    assert (after.status, after.error, after.report) == ("completed", None, record.report)


async def test_a_session_reclaimed_while_its_task_ran_is_not_overwritten_by_the_task() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    investigation_id, _ = await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    store.end_without_report(URL, investigation_id, "interrupted", store.STALE_ERROR, None, None)
    planner.release.set()
    await settle(deps)
    record, _ = read(investigation_id)
    assert record.status == "interrupted" and record.report is None


async def test_events_are_stored_while_the_session_runs() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    investigation_id, _ = await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    for _ in range(100):
        if planner.calls:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    record, timeline = read(investigation_id)
    assert record.status == "running" and record.report is None
    assert [e.event.kind for e in timeline][:1] == ["query"], "the opening query is already stored"
    planner.release.set()
    await settle(deps)


async def test_a_graceful_shutdown_ends_a_running_session_as_interrupted() -> None:
    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)
    investigation_id, _ = await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    for _ in range(100):
        if planner.calls:
            break
        await asyncio.sleep(0.01)
    await stop_active(deps)
    record, timeline = read(investigation_id)
    assert record.status == "interrupted" and "not resumed" in (record.error or "")
    assert timeline, "the progress made before the stop is kept"
    assert planner.calls == 1, "nothing restarted the work"


# The live path refuses to start what cannot run.


async def test_no_model_means_no_row() -> None:
    deps = deps_for("sparse-signal", None)
    with pytest.raises(StartRejectedError) as refused:
        await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    assert refused.value.status == 503
    assert sql("SELECT count(*) FROM investigations")[0][0] == 0


async def test_a_model_that_cannot_be_built_means_no_row() -> None:
    from finsentry.investigator.planning import PlanningError

    def broken() -> object:
        raise PlanningError("GEMINI_MODE is 'disabled', so there is no model to call")

    deps = deps_for("sparse-signal", GatedPlanner())
    deps.planner_factory = broken  # type: ignore[assignment]
    with pytest.raises(StartRejectedError) as refused:
        await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    assert refused.value.status == 503 and "GEMINI_MODE" in refused.value.message
    assert sql("SELECT count(*) FROM investigations")[0][0] == 0


async def test_a_tool_server_that_cannot_start_ends_the_session_as_failed() -> None:
    from contextlib import asynccontextmanager

    planner = GatedPlanner()
    deps = deps_for("sparse-signal", planner)

    @asynccontextmanager
    async def refuses():  # type: ignore[no-untyped-def]
        raise OSError("spawn failed")
        yield  # pragma: no cover

    deps.tool_session = refuses
    investigation_id, _ = await start_live(InvestigationRequest(kind="drift_degradation"), deps)
    await settle(deps)
    record, _ = read(investigation_id)
    assert record.status == "failed" and "tool server" in (record.error or "")
    assert planner.calls == 0


# A request is validated before anything is stored.


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "single_trace"},
        {"kind": "red_team_miss"},
        {"kind": "red_team_miss", "reference_id": "not-a-uuid"},
        {"kind": "drift_degradation", "reference_id": "abc"},
        {"kind": "not_a_trigger"},
        {"kind": "drift_degradation", "window_minutes": 0},
        {"kind": "drift_degradation", "window_minutes": 100000},
        {"kind": "drift_degradation", "unexpected": True},
    ],
)
def test_an_invalid_request_is_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        InvestigationRequest.model_validate(fields)


def test_a_valid_request_builds_its_trigger_scope_and_window() -> None:
    request = InvestigationRequest(
        kind="red_team_miss",
        reference_id="123e4567-e89b-42d3-a456-426614174000",
        endpoint="/rag/query",
        ticker="AAPL",
        window_minutes=30,
    )
    end = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    window = request.window(end)
    assert window.minutes == 30 and window.end == end
    assert request.trigger().reference_id == request.reference_id
    assert request.scope().endpoint == "/rag/query"
    assert request.key() == InvestigationRequest.model_validate(request.model_dump()).key()


def test_the_registered_case_ids_exist() -> None:
    for case_id in (
        seed.COMPLETED_DIAGNOSIS,
        seed.COMPLETED_REGRESSION,
        seed.JUSTIFIED_ABSTENTION,
        seed.UNAVAILABLE_SOURCE,
        seed.FAILED_RUN,
        seed.INTERRUPTED_RUN,
    ):
        assert case_id in CASES
