"""The typed interface mirrors the nine real tool functions exactly, and the server
registers exactly those nine as read-only."""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from finsentry.investigator.contracts import TOOL_NAMES
from finsentry.investigator.tool_contract import TOOL_CONTRACT_VERSION, McpReadTools
from finsentry.mcp import server as mcp_server
from finsentry.mcp.tools import drift, injections, judges, redteam, trace_evidence, traces

_REAL = {
    "get_failing_traces": traces.get_failing_traces,
    "explain_guardrail_decision": traces.explain_guardrail_decision,
    "get_judge_scores": judges.get_judge_scores,
    "search_prompt_injections": injections.search_prompt_injections,
    "get_drift_report": drift.get_drift_report,
    "search_traces": trace_evidence.search_traces,
    "get_trace_detail": trace_evidence.get_trace_detail,
    "list_red_team_executions": redteam.list_red_team_executions,
    "get_red_team_execution": redteam.get_red_team_execution,
}


def _params(fn: object) -> list[tuple[str, object, object]]:
    sig = inspect.signature(fn)  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in sig.parameters.values() if p.name != "self"]


def test_the_interface_covers_exactly_the_nine_tools() -> None:
    assert set(_REAL) == set(TOOL_NAMES)
    protocol_methods = {n for n, f in vars(McpReadTools).items() if inspect.iscoroutinefunction(f)}
    assert protocol_methods == set(TOOL_NAMES)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_each_method_matches_the_real_function(name: str) -> None:
    mirror = vars(McpReadTools)[name]
    real = _REAL[name]
    assert inspect.iscoroutinefunction(real)
    assert _params(mirror) == _params(real), "parameter names, kinds or defaults differ"
    hints_mirror = get_type_hints(mirror)
    hints_real = get_type_hints(real)
    assert hints_mirror == hints_real, "parameter or return types differ"


async def test_the_server_registers_exactly_these_nine_as_read_only() -> None:
    tools = await mcp_server.server.list_tools()
    assert {t.name for t in tools} == set(TOOL_NAMES)
    assert all(t.annotations is not None and t.annotations.read_only_hint for t in tools)


def test_the_contract_version_names_the_tool_surface() -> None:
    assert TOOL_CONTRACT_VERSION.startswith("mcp-read-9@")
    assert len(TOOL_CONTRACT_VERSION) == len("mcp-read-9@") + 12
