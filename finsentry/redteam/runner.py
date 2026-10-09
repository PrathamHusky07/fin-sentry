"""
Starts and runs a bounded red team run.

A run executes its scenarios one at a time, in order. One run may be active at once,
so the machine never carries two sets of rail inference. Every execution ends in a
persisted row: a harness error becomes execution_failed with a short reason, never a
silent skip and never a caught.
"""

from __future__ import annotations

import asyncio
import logging
import time

from finsentry.redteam import store
from finsentry.redteam.classify import Observation, classify
from finsentry.redteam.deps import Deps, ScenarioSetupError
from finsentry.redteam.exec_gateway import run as run_gateway_route
from finsentry.redteam.exec_output import run_output_rails
from finsentry.redteam.exec_rails import run_input_rails, run_retrieval_rail
from finsentry.redteam.models import Scenario
from finsentry.redteam.records import RunRequest
from finsentry.redteam.registry import load_scenarios

log = logging.getLogger(__name__)

PER_EXECUTION_SECONDS = 90.0
RUN_DEADLINE_SECONDS = 600.0

# A gateway_route scenario that no input rail stops goes on to the faithfulness rail and
# emits an event the flash judge scores, and either can call Gemini. The runner itself
# never calls a model, but it cannot keep a gateway request from continuing without
# changing the event contract. So it bounds the exposure instead: once this many gateway
# requests in one run have gone past the input rails, the run does not send another.
# Each Gemini call is still capped by the rails' own CostBudget.
MAX_CONTINUED_GATEWAY_REQUESTS = 1
_GATEWAY_STOP_REASON = (
    "Not run. An earlier gateway scenario in this run was not stopped by an input rail, "
    "so the request went on to the model path, where Gemini calls are possible. The run "
    "sends no further gateway requests. Start this scenario in a run of its own."
)

# Serializes starts within this process. Across processes the unique index from
# migration 006 is the guard: create_run raises RunAlreadyActiveError for the loser.
_start_lock = asyncio.Lock()
_tasks: set[asyncio.Task[None]] = set()


class RunRejectedError(Exception):
    """The request cannot start a run. `status` is the HTTP status the API answers."""

    def __init__(self, status: int, message: str, run_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.run_id = run_id


def resolve_scenarios(request: RunRequest) -> list[Scenario]:
    registry = load_scenarios()
    if request.scenario_ids is None:
        return [s for s in registry if s.mode == "deterministic"]
    if not request.scenario_ids:
        raise RunRejectedError(422, "Select at least one scenario.")
    if len(set(request.scenario_ids)) != len(request.scenario_ids):
        raise RunRejectedError(
            422, "A scenario can appear once per run. Start another run to rerun it."
        )
    by_id = {s.id: s for s in registry}
    unknown = [i for i in request.scenario_ids if i not in by_id]
    if unknown:
        raise RunRejectedError(422, f"Unknown scenario ids: {', '.join(unknown)}.")
    chosen = [by_id[i] for i in request.scenario_ids]
    judged = [s.id for s in chosen if s.mode == "judge_assisted"]
    if judged and not request.allow_judge_assisted:
        raise RunRejectedError(
            422, f"{', '.join(judged)} spends model calls. Set allow_judge_assisted to run it."
        )
    if judged and len(chosen) > 1:
        raise RunRejectedError(
            422, "A judge-assisted scenario runs alone, never as part of a suite."
        )
    return chosen


async def _execute(scenario: Scenario, deps: Deps, execution_id: str) -> Observation:
    match scenario.executor:
        case "gateway_route":
            return await run_gateway_route(scenario, deps, f"RT-{execution_id[:8]}")
        case "input_rails":
            return await run_input_rails(scenario, deps)
        case "retrieval_rail":
            return await run_retrieval_rail(scenario, deps)
        case "output_rails":
            return await run_output_rails(scenario, deps)


def _failure_reason(exc: Exception) -> str:
    # Only harness-authored messages are shown. Anything else could carry connection
    # details, so it is reduced to the exception type and the full error is logged.
    if isinstance(exc, ScenarioSetupError):
        return f"The scenario input could not be built: {exc}."
    if isinstance(exc, TimeoutError):
        return f"The execution exceeded its {PER_EXECUTION_SECONDS:g} second limit."
    return f"The harness raised {type(exc).__name__}. See the gateway log."


async def run_one(scenario: Scenario, deps: Deps, execution_id: str) -> bool:
    """Run one execution and persist it. Returns True when a gateway request may have gone
    past the input rails, which includes a gateway execution that raised or timed out."""
    url = deps.database_url
    await asyncio.to_thread(store.mark_running, url, execution_id)
    started = time.monotonic()
    try:
        async with asyncio.timeout(PER_EXECUTION_SECONDS):
            obs = await _execute(scenario, deps, execution_id)
        verdict = classify(scenario, obs)
        ms = int((time.monotonic() - started) * 1000)
        await asyncio.to_thread(
            store.finish_execution,
            url,
            execution_id,
            verdict.outcome,
            verdict,
            obs,
            verdict.reason,
            ms,
        )
        return obs.evidence.get("continued_past_input_rails") is True
    except Exception as exc:
        log.exception("red team execution %s of %s failed", execution_id, scenario.id)
        ms = int((time.monotonic() - started) * 1000)
        await asyncio.to_thread(
            store.finish_execution,
            url,
            execution_id,
            "execution_failed",
            None,
            None,
            _failure_reason(exc),
            ms,
        )
        return scenario.executor == "gateway_route"


async def run_suite(
    scenarios: list[Scenario], deps: Deps, run_id: str, execution_ids: list[str]
) -> None:
    failure: str | None = None
    continued = 0
    try:
        async with asyncio.timeout(RUN_DEADLINE_SECONDS):
            for scenario, execution_id in zip(scenarios, execution_ids, strict=True):
                if scenario.executor == "gateway_route" and continued >= (
                    MAX_CONTINUED_GATEWAY_REQUESTS
                ):
                    await asyncio.to_thread(
                        store.finish_execution,
                        deps.database_url,
                        execution_id,
                        "execution_failed",
                        None,
                        None,
                        _GATEWAY_STOP_REASON,
                        0,
                    )
                    continue
                if await run_one(scenario, deps, execution_id):
                    continued += 1
    except TimeoutError:
        failure = f"The run exceeded its {RUN_DEADLINE_SECONDS:g} second deadline."
    except Exception:
        log.exception("red team run %s stopped", run_id)
        failure = "The run stopped on an unexpected error. See the gateway log."
    try:
        if failure:
            await asyncio.to_thread(store.fail_unfinished, deps.database_url, run_id, failure)
        await asyncio.to_thread(store.finish_run, deps.database_url, run_id, failure)
    except Exception:
        log.exception("red team run %s could not be closed; stale reclaim will fail it", run_id)


async def start_run(request: RunRequest, deps: Deps) -> str:
    scenarios = resolve_scenarios(request)
    async with _start_lock:
        await asyncio.to_thread(store.reclaim_stale_runs, deps.database_url)
        active = await asyncio.to_thread(store.active_run_id, deps.database_url)
        if active is not None:
            raise RunRejectedError(409, "A run is already in progress.", run_id=active)
        try:
            run_id, execution_ids = await asyncio.to_thread(
                store.create_run, deps.database_url, scenarios, request.allow_judge_assisted
            )
        except store.RunAlreadyActiveError:
            # Another process won the race after the check above. The index decides.
            winner = await asyncio.to_thread(store.active_run_id, deps.database_url)
            raise RunRejectedError(409, "A run is already in progress.", run_id=winner) from None
    task = asyncio.create_task(run_suite(scenarios, deps, run_id, execution_ids))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return run_id
