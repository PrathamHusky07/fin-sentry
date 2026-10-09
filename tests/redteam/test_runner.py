"""Runner: scenario selection rules, execution_failed handling, and one active run at a time."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from finsentry.redteam import runner, store
from finsentry.redteam.classify import Observation
from finsentry.redteam.deps import ScenarioSetupError
from finsentry.redteam.records import RunRequest
from tests.conftest import TEST_DATABASE_URL
from tests.redteam.helpers import make_deps, scenario

_CAUGHT = Observation(
    summary="Blocked.",
    evidence={"gateway_status": 403, "gateway_rail": "prompt-guard-2"},
    defense_acted=True,
    acting_layer="prompt-guard-2",
    trace_ref="trace-9",
)


def _only_execution(run_id: str):  # type: ignore[no-untyped-def]
    detail = store.get_run(TEST_DATABASE_URL, run_id)
    assert detail is not None
    return detail[0], detail[1]


# --- scenario selection -------------------------------------------------


def test_a_default_run_is_every_deterministic_scenario_and_no_judge_assisted_one() -> None:
    chosen = runner.resolve_scenarios(RunRequest())
    assert len(chosen) == 9
    assert all(s.mode == "deterministic" for s in chosen)
    assert "OUT-003" not in [s.id for s in chosen]


def test_selection_keeps_the_requested_order() -> None:
    chosen = runner.resolve_scenarios(RunRequest(scenario_ids=["OUT-001", "DI-001"]))
    assert [s.id for s in chosen] == ["OUT-001", "DI-001"]


@pytest.mark.parametrize(
    ("request_body", "message"),
    [
        (RunRequest(scenario_ids=[]), "at least one"),
        (RunRequest(scenario_ids=["NOPE-001"]), "Unknown scenario ids: NOPE-001"),
        (RunRequest(scenario_ids=["DI-001", "DI-001"]), "once per run"),
        (RunRequest(scenario_ids=["OUT-003"]), "allow_judge_assisted"),
        (
            RunRequest(scenario_ids=["OUT-003", "DI-001"], allow_judge_assisted=True),
            "runs alone",
        ),
    ],
)
def test_invalid_selections_are_rejected_with_422(request_body: RunRequest, message: str) -> None:
    with pytest.raises(runner.RunRejectedError, match=message) as info:
        runner.resolve_scenarios(request_body)
    assert info.value.status == 422


def test_a_judge_assisted_scenario_runs_only_alone_and_on_explicit_opt_in() -> None:
    chosen = runner.resolve_scenarios(
        RunRequest(scenario_ids=["OUT-003"], allow_judge_assisted=True)
    )
    assert [s.id for s in chosen] == ["OUT-003"]


# --- one execution ------------------------------------------------------


async def _run_single(scenario_id: str, executor_result: object) -> tuple[str, object]:
    s = scenario(scenario_id)
    run_id, ids = store.create_run(TEST_DATABASE_URL, [s], False)

    async def fake(*_: object, **__: object) -> Observation:
        if isinstance(executor_result, BaseException):
            raise executor_result
        assert isinstance(executor_result, Observation)
        return executor_result

    with patch.object(runner, "_execute", fake):
        await runner.run_one(s, make_deps(), ids[0])
    return run_id, store.get_execution(TEST_DATABASE_URL, ids[0])


async def test_a_completed_execution_is_persisted_with_its_classification() -> None:
    _, row = await _run_single("DI-001", _CAUGHT)
    assert row.outcome == "caught" and row.expectation == "met"  # type: ignore[attr-defined]
    assert row.trace_ref == "trace-9" and row.state == "finished"  # type: ignore[attr-defined]


async def test_a_harness_exception_becomes_execution_failed_and_never_leaks_its_message() -> None:
    _, row = await _run_single("DI-001", RuntimeError("password=hunter2 host=db.internal"))
    assert row.outcome == "execution_failed"  # type: ignore[attr-defined]
    assert row.acting_layer is None  # type: ignore[attr-defined]
    assert "hunter2" not in row.reason  # type: ignore[attr-defined]
    assert "RuntimeError" in row.reason  # type: ignore[attr-defined]


async def test_a_scenario_setup_error_is_execution_failed_with_its_own_message() -> None:
    _, row = await _run_single(
        "IND-001", ScenarioSetupError("no corpus chunk exists for AAPL 10-K")
    )
    assert row.outcome == "execution_failed"  # type: ignore[attr-defined]
    assert "no corpus chunk exists for AAPL 10-K" in row.reason  # type: ignore[attr-defined]


async def test_an_execution_that_hangs_is_execution_failed_at_its_limit() -> None:
    async def hang(*_: object, **__: object) -> Observation:
        await asyncio.sleep(30)
        return _CAUGHT

    s = scenario("DI-001")
    _, ids = store.create_run(TEST_DATABASE_URL, [s], False)
    with (
        patch.object(runner, "_execute", hang),
        patch.object(runner, "PER_EXECUTION_SECONDS", 0.05),
    ):
        await runner.run_one(s, make_deps(), ids[0])
    row = store.get_execution(TEST_DATABASE_URL, ids[0])
    assert row is not None and row.outcome == "execution_failed"
    assert "second limit" in (row.reason or "")


async def test_an_unavailable_evaluator_is_persisted_as_such_with_no_acting_layer() -> None:
    down = Observation(summary="", unavailable_reason="An input rail could not run.")
    _, row = await _run_single("DI-001", down)
    assert row.outcome == "evaluator_unavailable"  # type: ignore[attr-defined]
    assert row.acting_layer is None and row.expectation == "not_assessable"  # type: ignore[attr-defined]


# --- a whole run --------------------------------------------------------


async def _wait_for_run(run_id: str) -> None:
    for _ in range(200):
        detail = store.get_run(TEST_DATABASE_URL, run_id)
        assert detail is not None
        if detail[0].status != "running":
            return
        await asyncio.sleep(0.02)
    raise AssertionError("run did not finish")


async def test_a_run_executes_scenarios_in_order_and_completes() -> None:
    order: list[str] = []

    async def fake(s: object, deps: object, execution_id: str) -> Observation:
        order.append(getattr(s, "id"))
        return _CAUGHT

    with patch.object(runner, "_execute", fake):
        run_id = await runner.start_run(
            RunRequest(scenario_ids=["DI-001", "HZ-001", "MS-001"]), make_deps()
        )
        await _wait_for_run(run_id)
    run, executions = _only_execution(run_id)
    assert order == ["DI-001", "HZ-001", "MS-001"]
    assert run.status == "completed" and (run.total, run.finished) == (3, 3)
    assert [e.seq for e in executions] == [0, 1, 2]


async def test_a_second_run_is_refused_while_one_is_active() -> None:
    release = asyncio.Event()

    async def slow(*_: object, **__: object) -> Observation:
        await release.wait()
        return _CAUGHT

    with patch.object(runner, "_execute", slow):
        first = await runner.start_run(RunRequest(scenario_ids=["DI-001"]), make_deps())
        with pytest.raises(runner.RunRejectedError) as info:
            await runner.start_run(RunRequest(scenario_ids=["DI-001"]), make_deps())
        assert info.value.status == 409 and info.value.run_id == first
        release.set()
        await _wait_for_run(first)


async def test_rerunning_after_completion_creates_a_new_run_and_new_executions() -> None:
    async def fake(*_: object, **__: object) -> Observation:
        return _CAUGHT

    with patch.object(runner, "_execute", fake):
        first = await runner.start_run(RunRequest(scenario_ids=["DI-001"]), make_deps())
        await _wait_for_run(first)
        second = await runner.start_run(RunRequest(scenario_ids=["DI-001"]), make_deps())
        await _wait_for_run(second)
    assert first != second
    assert len(store.list_executions(TEST_DATABASE_URL, 50, 0, scenario_id="DI-001")) == 2


async def test_a_run_past_its_deadline_fails_and_leaves_unfinished_executions_failed() -> None:
    async def slow(*_: object, **__: object) -> Observation:
        await asyncio.sleep(0.1)
        return _CAUGHT

    with (
        patch.object(runner, "_execute", slow),
        patch.object(runner, "RUN_DEADLINE_SECONDS", 0.15),
    ):
        run_id = await runner.start_run(
            RunRequest(scenario_ids=["DI-001", "HZ-001", "MS-001", "OUT-001"]), make_deps()
        )
        await _wait_for_run(run_id)
    run, executions = _only_execution(run_id)
    assert run.status == "failed" and "deadline" in (run.failure_reason or "")
    outcomes = [e.outcome for e in executions]
    assert "caught" in outcomes
    assert outcomes[-1] == "execution_failed"
    assert all(e.state == "finished" for e in executions)


# --- the gateway cost bound ---------------------------------------------

_PASSED_GATEWAY = Observation(
    summary="Passed.",
    evidence={"gateway_status": 200, "continued_past_input_rails": True},
    attack_passed=True,
)


async def test_after_one_gateway_request_goes_past_the_input_rails_no_more_are_sent() -> None:
    sent: list[str] = []

    async def fake(s: object, deps: object, execution_id: str) -> Observation:
        sent.append(getattr(s, "id"))
        return _PASSED_GATEWAY if getattr(s, "executor") == "gateway_route" else _CAUGHT

    with patch.object(runner, "_execute", fake):
        run_id = await runner.start_run(
            RunRequest(scenario_ids=["DI-001", "HZ-001", "OUT-001", "MS-001"]), make_deps()
        )
        await _wait_for_run(run_id)
    run, executions = _only_execution(run_id)
    # DI-001 went on, so HZ-001 and MS-001 are never sent. The non-gateway scenario still runs.
    assert sent == ["DI-001", "OUT-001"]
    assert [e.outcome for e in executions][:2] == ["missed", "execution_failed"]
    assert executions[3].outcome == "execution_failed"
    assert "Not run" not in (executions[2].reason or "")
    assert all(e.state == "finished" for e in executions)
    assert "Not run" in (executions[1].reason or "")
    assert executions[1].gemini_calls == 0 and executions[1].duration_ms == 0
    assert run.status == "completed"


async def test_gateway_requests_stopped_by_an_input_rail_do_not_use_up_the_bound() -> None:
    sent: list[str] = []

    async def fake(s: object, deps: object, execution_id: str) -> Observation:
        sent.append(getattr(s, "id"))
        return Observation(
            summary="Blocked.",
            evidence={
                "gateway_status": 403,
                "gateway_rail": "prompt-guard-2",
                "continued_past_input_rails": False,
            },
            defense_acted=True,
            acting_layer="prompt-guard-2",
        )

    with patch.object(runner, "_execute", fake):
        run_id = await runner.start_run(
            RunRequest(scenario_ids=["DI-001", "HZ-001", "MS-001"]), make_deps()
        )
        await _wait_for_run(run_id)
    assert sent == ["DI-001", "HZ-001", "MS-001"]


async def test_a_gateway_execution_that_raised_counts_as_having_gone_past_the_input_rails() -> None:
    async def boom(*_: object, **__: object) -> Observation:
        raise RuntimeError("connection reset")

    with patch.object(runner, "_execute", boom):
        run_id = await runner.start_run(RunRequest(scenario_ids=["DI-001", "HZ-001"]), make_deps())
        await _wait_for_run(run_id)
    _, executions = _only_execution(run_id)
    assert "Not run" in (executions[1].reason or "")


# --- one active run across processes ------------------------------------
# These start two separate Python processes against the real test database. Each has its
# own asyncio.Lock, so only the partial unique index from migration 006 can keep them
# from both creating a running run.


def _race_two_processes(force_race: bool) -> list[dict[str, object]]:
    start_at = time.time() + 4.0  # interpreter and import time for both children
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.redteam.concurrent_start",
                str(start_at),
                str(int(force_race)),
            ],
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, "TEST_DATABASE_URL": TEST_DATABASE_URL},
        )
        for _ in range(2)
    ]
    results: list[dict[str, object]] = []
    for child in children:
        out, _ = child.communicate(timeout=60)
        assert child.returncode == 0, out
        results.append(json.loads(out.strip().splitlines()[0]))
    return results


@pytest.mark.parametrize("force_race", [False, True], ids=["natural_timing", "both_pass_the_check"])
def test_two_processes_starting_at_once_leave_exactly_one_active_run(force_race: bool) -> None:
    results = _race_two_processes(force_race)
    winners = [r for r in results if "started" in r]
    losers = [r for r in results if "rejected" in r]
    assert len(winners) == 1 and len(losers) == 1, results
    assert losers[0]["rejected"] == 409
    assert losers[0]["run_id"] == winners[0]["started"]
    runs = store.list_runs(TEST_DATABASE_URL, 10)
    assert [r.run_id for r in runs] == [winners[0]["started"]]
    assert runs[0].total == 1


def test_the_database_refuses_a_second_running_run_but_not_a_second_finished_one() -> None:
    first, _ = store.create_run(TEST_DATABASE_URL, [scenario("DI-001")], False)
    with pytest.raises(store.RunAlreadyActiveError):
        store.create_run(TEST_DATABASE_URL, [scenario("HZ-001")], False)
    store.finish_run(TEST_DATABASE_URL, first, None)
    second, _ = store.create_run(TEST_DATABASE_URL, [scenario("DI-001")], False)
    store.finish_run(TEST_DATABASE_URL, second, None)
    assert len(store.list_runs(TEST_DATABASE_URL, 10)) == 2
