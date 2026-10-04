"""
Proves the MCP server's registered tool surface is exactly the five backed
Day 7 tools -- run_red_team_scenario is deliberately absent (deferred to
Day 10, no stored-scenario registry exists yet).
"""
from __future__ import annotations

from finsentry.mcp.server import server

_EXPECTED_BACKED_TOOLS = {
    "get_failing_traces",
    "explain_guardrail_decision",
    "get_judge_scores",
    "search_prompt_injections",
    "get_drift_report",
}


async def test_registered_tools_are_exactly_the_five_backed_tools() -> None:
    tools = await server.list_tools()
    names = {t.name for t in tools}

    assert names == _EXPECTED_BACKED_TOOLS
    assert "run_red_team_scenario" not in names
