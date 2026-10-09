from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from finsentry.mcp.tools.redteam import get_red_team_execution, list_red_team_executions
from finsentry.redteam import store
from finsentry.redteam.classify import Classification, Observation
from finsentry.redteam.registry import get_scenario
from tests.conftest import TEST_DATABASE_URL

_MISSING = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)

    def wipe() -> None:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM red_team_executions")
            conn.execute("DELETE FROM red_team_runs")

    wipe()
    yield
    wipe()


def _store_run(*scenario_ids: str, outcomes: tuple[str, ...]) -> tuple[str, list[str]]:
    scenarios = [s for i in scenario_ids if (s := get_scenario(i)) is not None]
    run_id, ids = store.create_run(TEST_DATABASE_URL, scenarios, False)
    for execution_id, outcome in zip(ids, outcomes, strict=True):
        caught = outcome == "caught"
        obs = Observation(
            summary="Blocked." if caught else "Passed.",
            evidence={"gateway_status": 403 if caught else 200},
            defense_acted=caught,
            attack_passed=not caught,
            trace_ref="trace-1",
        )
        verdict = Classification(
            outcome,  # type: ignore[arg-type]
            "met" if caught else "not_met",
            obs.summary,
            "prompt-guard-2" if caught else None,
        )
        store.finish_execution(
            TEST_DATABASE_URL,
            execution_id,
            outcome,
            verdict,
            obs,
            verdict.reason,
            12,  # type: ignore[arg-type]
        )
    store.finish_run(TEST_DATABASE_URL, run_id, None)
    return run_id, ids


def _snapshot() -> list[tuple[object, ...]]:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        runs = conn.execute("SELECT * FROM red_team_runs ORDER BY run_id").fetchall()
        executions = conn.execute("SELECT * FROM red_team_executions ORDER BY execution_id")
        return [*runs, *executions.fetchall()]


async def test_list_returns_the_persisted_execution_records_in_scenario_order() -> None:
    run_id, ids = _store_run("DI-001", "HZ-001", outcomes=("caught", "missed"))

    page = await list_red_team_executions()

    assert [e.execution_id for e in page.executions] == ids
    first = page.executions[0]
    assert (first.run_id, first.scenario_id, first.outcome, first.expectation) == (
        run_id,
        "DI-001",
        "caught",
        "met",
    )
    assert first.expected.outcome == "caught"  # the hypothesis is kept apart from the result
    assert first.evidence == {"gateway_status": 403}
    assert first.trace_ref == "trace-1"
    assert page.next_offset is None


async def test_list_filters_and_pages() -> None:
    run_id, _ = _store_run("DI-001", "HZ-001", outcomes=("caught", "missed"))
    other_run, _ = _store_run("MS-001", outcomes=("missed",))

    missed = await list_red_team_executions(outcome="missed")
    assert {e.scenario_id for e in missed.executions} == {"HZ-001", "MS-001"}
    assert [e.scenario_id for e in (await list_red_team_executions(run_id=run_id)).executions] == [
        "DI-001",
        "HZ-001",
    ]
    assert len((await list_red_team_executions(scenario_id="MS-001")).executions) == 1
    first_page = await list_red_team_executions(limit=2)
    assert len(first_page.executions) == 2 and first_page.next_offset == 2
    assert other_run == first_page.executions[0].run_id  # newest run first


@pytest.mark.parametrize("limit", [0, 101])
async def test_list_bounds_the_page_size(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be"):
        await list_red_team_executions(limit=limit)


async def test_list_rejects_a_bad_offset_run_id_and_scenario_id() -> None:
    with pytest.raises(ValueError, match="offset"):
        await list_red_team_executions(offset=-1)
    with pytest.raises(ValueError, match="run_id must be a UUID"):
        await list_red_team_executions(run_id="not-a-uuid")
    with pytest.raises(ValueError, match="scenario_id"):
        await list_red_team_executions(scenario_id="x" * 17)


async def test_get_returns_one_execution_with_its_evidence() -> None:
    _, ids = _store_run("DI-001", outcomes=("caught",))

    result = await get_red_team_execution(ids[0])

    assert result.found is True and result.execution is not None
    assert result.execution.execution_id == ids[0]
    assert result.execution.reason == "Blocked."
    assert result.execution.duration_ms == 12


async def test_get_reports_found_false_for_an_unknown_execution() -> None:
    result = await get_red_team_execution(_MISSING)
    assert (result.found, result.execution) == (False, None)


async def test_get_rejects_a_malformed_execution_id() -> None:
    with pytest.raises(ValueError, match="execution_id must be a UUID"):
        await get_red_team_execution("1; DROP TABLE red_team_runs")


async def test_without_a_database_url_the_tools_raise_instead_of_returning_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        await list_red_team_executions()
    with pytest.raises(ValueError, match="DATABASE_URL"):
        await get_red_team_execution(_MISSING)


async def test_the_red_team_tools_change_nothing_in_the_store() -> None:
    _, ids = _store_run("DI-001", "HZ-001", outcomes=("caught", "missed"))
    before = _snapshot()

    await list_red_team_executions()
    await list_red_team_executions(outcome="missed", limit=1, offset=0)
    await get_red_team_execution(ids[0])
    await get_red_team_execution(_MISSING)

    assert _snapshot() == before
