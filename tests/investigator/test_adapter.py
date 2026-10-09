"""The adapter separates a tool that could not run from a tool that found nothing, and it
can only reach the nine read tools."""

from __future__ import annotations

from typing import Any

import pytest

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import KNOWN_TOOL_GAPS, ReadOnlyAdapter
from finsentry.investigator.contracts import EvidenceRef


class _Tools:
    """A tool object whose every method returns or raises what the test set."""

    def __init__(self, **outcomes: object) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        async def call(**_: object) -> object:
            self.calls.append(name)
            outcome = self._outcomes[name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return call


async def _call(tool: str, outcome: object, **args: object):
    return await ReadOnlyAdapter(_Tools(**{tool: outcome})).call(tool, "q1", **args)  # type: ignore[arg-type]


async def test_an_offline_tool_with_an_empty_list_is_unavailable_not_empty() -> None:
    offline = fx.failing_traces_result([], connected=False)
    result = await _call("get_failing_traces", offline)
    assert result.status == "unavailable"
    assert result.evidence == []  # nothing was learned, so nothing is citable
    assert result.error is not None and "offline" in result.error


async def test_a_connected_tool_with_no_rows_is_empty_and_the_query_is_citable() -> None:
    result = await _call("get_failing_traces", fx.failing_traces_result([]))
    assert result.status == "empty"
    assert result.evidence == [EvidenceRef(kind="query_result", record_id="q1")]


async def test_returned_traces_become_citable_evidence() -> None:
    traces = [fx.failing_trace("t1"), fx.failing_trace("t2"), fx.failing_trace("t1")]
    result = await _call("get_failing_traces", fx.failing_traces_result(traces))
    assert result.status == "ok"
    assert result.evidence == [
        EvidenceRef(kind="query_result", record_id="q1"),
        EvidenceRef(kind="trace", record_id="t1"),
        EvidenceRef(kind="trace", record_id="t2"),
    ]


async def test_a_tool_that_raises_is_unavailable_with_the_error_kept() -> None:
    result = await _call("search_traces", RuntimeError("RisingWave query failed"))
    assert result.status == "unavailable"
    assert result.payload is None
    assert result.error == "RuntimeError: RisingWave query failed"


async def test_a_tool_that_refuses_its_arguments_is_rejected_not_unavailable() -> None:
    result = await _call("search_traces", ValueError("limit must be <= 100, got 500"), limit=500)
    assert result.status == "rejected"
    assert "limit" in (result.error or "")


async def test_every_tool_family_tells_offline_from_empty_from_data() -> None:
    cases = {
        "explain_guardrail_decision": (
            fx.guardrail_decision("t", found=False, connected=False),
            fx.guardrail_decision("t", found=False),
            fx.guardrail_decision("t"),
        ),
        "get_judge_scores": (
            fx.judge_scores("t", [], connected=False),
            fx.judge_scores("t", []),
            fx.judge_scores("t", [fx.judge_verdict()]),
        ),
        "search_prompt_injections": (
            fx.injections_result([], connected=False),
            fx.injections_result([]),
            fx.injections_result([fx.injection_event("t")]),
        ),
        "get_trace_detail": (
            fx.missing_trace_detail("t", connected=False),
            fx.missing_trace_detail("t"),
            fx.trace_detail("t"),
        ),
    }
    for tool, (offline, empty, data) in cases.items():
        assert (await _call(tool, offline, app_trace_id="t")).status == "unavailable", tool
        assert (await _call(tool, empty, app_trace_id="t")).status == "empty", tool
        assert (await _call(tool, data, app_trace_id="t")).status == "ok", tool


async def test_trace_list_and_drift_and_red_team_results() -> None:
    from finsentry.events.trace_api import TraceListResponse
    from finsentry.redteam.records import ExecutionList

    def listing(items: list[Any], connected: bool = True) -> TraceListResponse:
        return TraceListResponse(traces=items, next_offset=None, risingwave_connected=connected)

    assert (await _call("search_traces", listing([], False))).status == "unavailable"
    assert (await _call("search_traces", listing([]))).status == "empty"
    assert (await _call("search_traces", listing([fx.trace_item("t")]))).status == "ok"
    assert (await _call("get_drift_report", fx.drift_report(state=None))).status == "empty"
    drift = await _call("get_drift_report", fx.drift_report())
    assert drift.evidence[-1] == EvidenceRef(kind="drift_report", record_id="gemini-rubric")
    run = fx.execution(
        "e1", "DI-001", "direct_injection", outcome="caught", expected_caught_by="prompt-guard-2"
    )
    assert (
        await _call("list_red_team_executions", ExecutionList(executions=[], next_offset=None))
    ).status == "empty"
    listed = await _call(
        "list_red_team_executions", ExecutionList(executions=[run], next_offset=None)
    )
    assert listed.evidence[-1] == EvidenceRef(kind="red_team_execution", record_id="e1")


async def test_a_tool_outside_the_nine_cannot_be_called() -> None:
    tools = _Tools()
    adapter = ReadOnlyAdapter(tools)  # type: ignore[arg-type]
    for name in ("run_red_team_scenario", "write_db", "__class__", "dao"):
        with pytest.raises(ValueError, match="not one of the nine"):
            await adapter.call(name, "q1")
    assert tools.calls == []


def test_the_known_gaps_include_the_silent_empty_on_a_failed_query() -> None:
    assert any("failed SQL query" in g.detail for g in KNOWN_TOOL_GAPS)
