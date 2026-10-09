"""A SQL failure on a connected pool must not read as "nothing happened".

The four RisingWave tools that go through fetch_all return an empty result with
risingwave_connected true when their query fails. The signal that tells the two apart lives
in the DAO, so it is only reachable where the adapter shares a process with the DAO. Where it
is not (the stdio server), an empty result from those tools is marked unverified instead.
"""

from __future__ import annotations

from typing import Any

import pytest

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import ToolName
from finsentry.investigator.evaluation.world import FixtureWorld, WorldData

FETCH_ALL_TOOLS: list[tuple[ToolName, dict[str, Any]]] = [
    ("get_failing_traces", {"failure_type": "blocked", "time_window_minutes": 60}),
    ("explain_guardrail_decision", {"app_trace_id": "t1"}),
    ("get_judge_scores", {"app_trace_id": "t1"}),
    ("search_prompt_injections", {"time_window_minutes": 60}),
]


def _adapter(world: FixtureWorld, *, probe: bool) -> ReadOnlyAdapter:
    return ReadOnlyAdapter(
        world, failure_probe=(lambda: world.failed_query_count) if probe else None
    )


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_a_failed_query_is_unavailable_not_empty(
    tool: ToolName, args: dict[str, Any]
) -> None:
    world = FixtureWorld(WorldData(failing_queries=frozenset({tool})))
    result = await _adapter(world, probe=True).call(tool, "q1", **args)
    assert result.status == "unavailable"
    assert result.evidence == []
    assert result.error is not None and "query failed" in result.error


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_a_successful_query_with_no_rows_is_a_verified_empty(
    tool: ToolName, args: dict[str, Any]
) -> None:
    world = FixtureWorld(WorldData())
    result = await _adapter(world, probe=True).call(tool, "q1", **args)
    assert result.status == "empty"
    assert result.empty_unverified is False
    assert result.evidence and result.evidence[0].kind == "query_result"


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_without_the_signal_an_empty_result_is_marked_unverified(
    tool: ToolName, args: dict[str, Any]
) -> None:
    failed = FixtureWorld(WorldData(failing_queries=frozenset({tool})))
    fine = FixtureWorld(WorldData())
    for world in (failed, fine):  # the two cannot be told apart, so both are unverified
        result = await _adapter(world, probe=False).call(tool, "q1", **args)
        assert result.status == "empty" and result.empty_unverified is True


async def test_tools_that_raise_on_failure_are_never_marked_unverified() -> None:
    world = FixtureWorld(WorldData())
    result = await _adapter(world, probe=False).call("search_traces", "q1", limit=5)
    assert result.status == "empty" and result.empty_unverified is False


async def test_a_failure_during_a_call_that_still_returned_rows_is_unavailable() -> None:
    """get_failing_traces with failure_type any runs two queries. One can fail while the
    other returns rows, so partial data must not be read as the whole picture."""
    count = {"n": 0}

    class Partial:
        async def get_failing_traces(self, **_: object) -> object:
            count["n"] += 1
            return fx.failing_traces_result([fx.failing_trace("t1")])

    result = await ReadOnlyAdapter(Partial(), failure_probe=lambda: count["n"]).call(  # type: ignore[arg-type]
        "get_failing_traces", "q1", failure_type="any"
    )
    assert result.status == "unavailable" and result.evidence == []
