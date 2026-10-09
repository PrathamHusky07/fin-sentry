"""
Proves the MCP server's registered tool surface is exactly the five Day 7 tools
plus the four read-only investigation tools, and that every one is marked
read-only. run_red_team_scenario is deliberately absent: whether an agent may
start a run is a Day 11 decision.
"""

from __future__ import annotations

from finsentry.mcp.server import server

_EXPECTED_TOOLS = {
    "get_failing_traces",
    "explain_guardrail_decision",
    "get_judge_scores",
    "search_prompt_injections",
    "get_drift_report",
    "search_traces",
    "get_trace_detail",
    "list_red_team_executions",
    "get_red_team_execution",
}


async def test_registered_tools_are_exactly_the_nine_read_only_tools() -> None:
    tools = await server.list_tools()
    names = {t.name for t in tools}

    assert names == _EXPECTED_TOOLS
    assert "run_red_team_scenario" not in names


async def test_every_registered_tool_is_marked_read_only() -> None:
    for tool in await server.list_tools():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is True, tool.name
        assert not tool.annotations.destructive_hint, tool.name
