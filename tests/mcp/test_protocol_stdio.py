"""
Real MCP protocol-boundary smoke test: launches the server as an actual
subprocess via its real entrypoint (python -m finsentry.mcp.server) and
drives it over real stdio JSON-RPC with the installed SDK's own client
(mcp.Client). test_server.py proves tool registration in-process; this test
proves the wire protocol itself -- handshake, listing, schema exposure,
a real tools/call round trip, and argument validation -- actually works
across a process boundary.

Kept deterministic and infra-free: RISINGWAVE_PORT is overridden to an
unused port so the subprocess's dao.open() always fails the same way into
offline mode, regardless of whatever is or isn't running on this machine,
and the one tool call exercised (get_drift_report) reads only on-disk
artifacts and the live DriftConfig -- no RisingWave access at all. The live
demo (scripts/mcp_investigation_demo_d7.py) remains the separate real-data
integration proof against actual RisingWave.

This test takes ~30s: psycopg_pool retries the refused connection with
backoff for its full open(wait=True) default timeout before dao.open()
gives up and falls back to offline mode -- real, pre-existing DAO behavior,
not something introduced here.
"""

from __future__ import annotations

import os
import sys

from mcp import Client, StdioServerParameters

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


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env["RISINGWAVE_PORT"] = "1"  # nothing listens here: fast, deterministic offline mode
    env["OTEL_EXPORTER"] = "none"
    return StdioServerParameters(
        command=sys.executable, args=["-m", "finsentry.mcp.server"], env=env
    )


async def test_stdio_protocol_handshake_listing_call_and_validation() -> None:
    async with Client(_server_params()) as client:
        # Handshake: server identity.
        assert client.server_info is not None
        assert client.server_info.name == "finsentry-ops"
        assert client.server_info.version == "0.1.0"

        # tools/list: exactly the nine read-only tools, schemas exposed.
        listing = await client.list_tools()
        names = {t.name for t in listing.tools}
        assert names == _EXPECTED_TOOLS
        assert "run_red_team_scenario" not in names
        for tool in listing.tools:
            assert tool.input_schema.get("type") == "object"

        # tools/call: a real read-only call with no infra dependency.
        result = await client.call_tool("get_drift_report", {})
        assert result.is_error is False
        assert result.structured_content["judge_id"] == "gemini-rubric"
        assert "policy" in result.structured_content

        # Invalid arguments (missing required field) are rejected as a tool-level
        # error result, not silently coerced or executed -- this SDK reports
        # argument-validation failures via CallToolResult(is_error=True), not a
        # JSON-RPC-level MCPError (see mcp.server.mcpserver.server._handle_call_tool).
        invalid = await client.call_tool("get_judge_scores", {})
        assert invalid.is_error is True

    # Clean shutdown: exiting the `async with` closed the subprocess without raising.
