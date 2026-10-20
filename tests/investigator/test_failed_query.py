"""A SQL failure on a connected pool must not read as "nothing happened".

The four row-reading tools raise when their query fails, so the adapter reports unavailable.
A tools object that does not say it raises may be a server that predates the fix, and an
empty result from it is marked unverified instead. A query that matched nothing is a verified
empty over a client that declares the raise.
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


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_a_failed_query_is_unavailable_not_empty(
    tool: ToolName, args: dict[str, Any]
) -> None:
    world = FixtureWorld(WorldData(failing_queries=frozenset({tool})))
    result = await ReadOnlyAdapter(world).call(tool, "q1", **args)
    assert result.status == "unavailable"
    assert result.evidence == []
    assert result.error is not None and "query failed" in result.error


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_a_successful_query_with_no_rows_is_a_verified_empty(
    tool: ToolName, args: dict[str, Any]
) -> None:
    result = await ReadOnlyAdapter(FixtureWorld(WorldData())).call(tool, "q1", **args)
    assert result.status == "empty"
    assert result.empty_unverified is False
    assert result.evidence and result.evidence[0].kind == "query_result"


@pytest.mark.parametrize("tool, args", FETCH_ALL_TOOLS, ids=[t for t, _ in FETCH_ALL_TOOLS])
async def test_a_server_that_does_not_raise_leaves_an_empty_result_marked_unverified(
    tool: ToolName, args: dict[str, Any]
) -> None:
    """A world that models a server predating the fix: the failure returns an empty result, so
    it cannot be told from no rows, and neither is trusted."""
    for data in (WorldData(failing_queries=frozenset({tool})), WorldData()):
        world = FixtureWorld(data, failed_query_raises=False)
        result = await ReadOnlyAdapter(_Undeclared(world)).call(tool, "q1", **args)
        assert result.status == "empty" and result.empty_unverified is True


class _Undeclared:
    """A tools object that makes no claim about how it reports a failed query."""

    def __init__(self, inner: FixtureWorld) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name == "failed_query_raises":
            raise AttributeError(name)
        return getattr(self._inner, name)


async def test_tools_that_raise_on_failure_are_never_marked_unverified() -> None:
    world = FixtureWorld(WorldData())
    result = await ReadOnlyAdapter(world).call("search_traces", "q1", limit=5)
    assert result.status == "empty" and result.empty_unverified is False


async def test_a_failure_in_one_of_two_queries_does_not_return_the_rows_of_the_other() -> None:
    """get_failing_traces with failure_type any runs two queries. If either fails the tool
    raises, so partial data is never read as the whole picture."""

    class Partial:
        failed_query_raises = True

        async def get_failing_traces(self, **_: object) -> object:
            raise RuntimeError("second query failed")

    result = await ReadOnlyAdapter(Partial()).call(  # type: ignore[arg-type]
        "get_failing_traces", "q1", failure_type="any"
    )
    assert result.status == "unavailable" and result.evidence == []


async def test_rows_from_a_healthy_query_are_still_ok() -> None:
    world = FixtureWorld(WorldData(failing=(fx.failing_trace("t1"),)))
    result = await ReadOnlyAdapter(world).call("get_failing_traces", "q1", failure_type="blocked")
    assert result.status == "ok"
