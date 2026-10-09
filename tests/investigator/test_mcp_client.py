"""The investigator's MCP client, over the official SDK, against the real tool functions.

The in-process tests register the nine real tool functions on an MCPServer and talk to it
through the SDK client, so the wire protocol, the tool schemas and the error rendering are the
real ones. Only the data sources behind the tools are replaced. test_the_real_stdio_server_*
launches the actual entry point as a subprocess.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from finsentry.investigator.adapter import ReadOnlyAdapter, ToolResult
from finsentry.investigator.contracts import TOOL_NAMES
from finsentry.investigator.mcp_client import (
    McpToolClient,
    UnsafeToolSurfaceError,
    check_tool_surface,
    connect_read_tools,
    stdio_parameters,
)
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.mcp.state import dao
from finsentry.mcp.tools.drift import get_drift_report
from finsentry.mcp.tools.injections import search_prompt_injections
from finsentry.mcp.tools.judges import get_judge_scores
from finsentry.mcp.tools.redteam import get_red_team_execution, list_red_team_executions
from finsentry.mcp.tools.trace_evidence import get_trace_detail, search_traces
from finsentry.mcp.tools.traces import explain_guardrail_decision, get_failing_traces
from finsentry.risingwave.dao import RisingWaveQueryError

NINE = (
    get_failing_traces,
    explain_guardrail_decision,
    get_judge_scores,
    search_prompt_injections,
    get_drift_report,
    search_traces,
    get_trace_detail,
    list_red_team_executions,
    get_red_team_execution,
)
READ_ONLY = ToolAnnotations(read_only_hint=True)
UUID = "00000000-0000-0000-0000-000000000001"


def _server(*extra: Any, annotate: bool = True) -> MCPServer:
    server: MCPServer = MCPServer(name="test-ops")
    for tool in (*NINE, *extra):
        server.add_tool(tool, annotations=READ_ONLY if annotate else None)
    return server


@asynccontextmanager
async def _adapter(server: MCPServer | None = None) -> AsyncIterator[ReadOnlyAdapter]:
    async with connect_read_tools(server or _server()) as tools:
        yield ReadOnlyAdapter(tools, failure_probe=lambda: dao.failed_query_count)


@pytest.fixture(autouse=True)
def _sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connected RisingWave pool that returns no rows, and no Red Team store."""
    monkeypatch.setattr(dao, "_pool", object())

    async def no_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(dao, "query_all", no_rows)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _no_evidence(result: ToolResult) -> None:
    assert result.evidence == [], "a call that learned nothing must cite nothing"


# The tool surface.


async def test_the_real_tool_set_is_exactly_the_nine_read_only_tools() -> None:
    async with Client(_server()) as client:
        tools = (await client.list_tools()).tools
    check_tool_surface(tools)
    assert {t.name for t in tools} == set(TOOL_NAMES)


async def test_a_server_that_also_offers_a_mutating_tool_is_refused() -> None:
    async def run_red_team_scenario(scenario_id: str) -> dict[str, str]:
        return {"started": scenario_id}

    with pytest.raises(UnsafeToolSurfaceError, match="run_red_team_scenario"):
        async with connect_read_tools(_server(run_red_team_scenario)):
            raise AssertionError("connected to an unsafe server")


async def test_a_server_whose_tools_are_not_marked_read_only_is_refused() -> None:
    with pytest.raises(UnsafeToolSurfaceError, match="read-only"):
        async with connect_read_tools(_server(annotate=False)):
            raise AssertionError("connected to an unannotated server")


async def test_a_server_missing_a_tool_is_refused() -> None:
    server: MCPServer = MCPServer(name="partial")
    for tool in NINE[:-1]:
        server.add_tool(tool, annotations=READ_ONLY)
    with pytest.raises(UnsafeToolSurfaceError, match="get_red_team_execution"):
        async with connect_read_tools(server):
            raise AssertionError("connected to a partial server")


async def test_no_other_tool_can_be_reached_through_the_adapter_or_the_client() -> None:
    async with _adapter() as adapter:
        with pytest.raises(ValueError, match="not one of the nine"):
            await adapter.call("run_red_team_scenario", "q1", scenario_id="DI-001")
        assert adapter.calls_made == 0
    assert not hasattr(McpToolClient, "run_red_team_scenario")
    assert not hasattr(McpToolClient, "call_tool")


def test_the_client_has_the_same_signatures_as_the_tool_contract() -> None:
    for name in TOOL_NAMES:
        assert inspect.signature(getattr(McpToolClient, name)) == inspect.signature(
            getattr(McpReadTools, name)
        ), name


# Each outcome maps to the right status and fabricates no evidence.


async def test_a_genuine_empty_result_is_empty_and_verified() -> None:
    async with _adapter() as adapter:
        result = await adapter.call("get_judge_scores", "q1", app_trace_id="t-none")
    assert result.status == "empty" and result.empty_unverified is False
    assert [e.kind for e in result.evidence] == ["query_result"]


async def test_a_genuinely_empty_red_team_store_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from finsentry.mcp.tools import redteam

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(redteam.store, "list_executions", lambda *a, **k: [])
    async with _adapter() as adapter:
        result = await adapter.call("list_red_team_executions", "q1", limit=5)
    assert result.status == "empty"


async def test_an_offline_source_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dao, "_pool", None)
    async with _adapter() as adapter:
        result = await adapter.call("get_failing_traces", "q1", failure_type="blocked")
    assert result.status == "unavailable"
    _no_evidence(result)


async def test_a_failed_query_on_a_connected_pool_is_unavailable_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fails(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        raise RisingWaveQueryError("RisingWave query failed")

    monkeypatch.setattr(dao, "query_all", fails)
    async with _adapter() as adapter:
        result = await adapter.call("get_judge_scores", "q1", app_trace_id="t1")
    assert result.status == "unavailable" and result.error is not None
    _no_evidence(result)


async def test_without_the_dao_signal_the_same_failure_is_an_unverified_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fails(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        raise RisingWaveQueryError("RisingWave query failed")

    monkeypatch.setattr(dao, "query_all", fails)
    async with connect_read_tools(_server()) as tools:
        result = await ReadOnlyAdapter(tools).call("get_judge_scores", "q1", app_trace_id="t1")
    assert result.status == "empty" and result.empty_unverified is True


async def test_an_unset_red_team_store_is_unavailable() -> None:
    async with _adapter() as adapter:
        result = await adapter.call("get_red_team_execution", "q1", execution_id=UUID)
    assert result.status == "unavailable"
    _no_evidence(result)


async def test_a_backend_error_inside_a_tool_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finsentry.mcp.tools import redteam

    def store_down(*_: object, **__: object) -> None:
        raise ConnectionError("the red team store dropped the connection")

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(redteam.store, "list_executions", store_down)
    async with _adapter() as adapter:
        result = await adapter.call("list_red_team_executions", "q1", limit=5)
    assert result.status == "unavailable" and result.error is not None
    _no_evidence(result)


@pytest.mark.parametrize(
    "tool, args",
    [
        ("get_failing_traces", {"limit": 0}),
        ("get_failing_traces", {"limit": 501}),
        ("search_traces", {"limit": 101}),
        ("search_traces", {"offset": -1}),
        ("search_traces", {"bogus": 1}),
        ("get_failing_traces", {"failure_type": "everything"}),
        ("get_red_team_execution", {"execution_id": "not-a-uuid"}),
        ("list_red_team_executions", {"scenario_id": "x" * 17}),
        ("get_trace_detail", {}),
    ],
)
async def test_invalid_arguments_are_rejected_before_any_call(
    tool: str, args: dict[str, Any]
) -> None:
    async with _adapter() as adapter:
        result = await adapter.call(tool, "q1", **args)
    assert result.status == "rejected" and result.error is not None
    _no_evidence(result)


async def test_the_server_hides_why_a_call_failed_so_the_check_must_come_first() -> None:
    """Both a bad argument the schema cannot see and a dead backend arrive as the same
    opaque text. This is why tool_args decides rejected from unavailable before the call."""
    async with Client(_server()) as client:
        bad = await client.call_tool("search_traces", {"limit": 0})
        down = await client.call_tool("get_red_team_execution", {"execution_id": UUID})
    assert bad.is_error and down.is_error
    assert bad.content[0].text == down.content[0].text.replace(
        "get_red_team_execution", "search_traces"
    )  # type: ignore[union-attr]


# The real entry point over stdio. RisingWave is pointed at a closed port and the Red Team
# store at nothing, so the run does not depend on what is up on this machine. It takes about
# 30 seconds because the pool retries before it falls back to offline mode.


async def test_the_real_stdio_server_exposes_only_the_nine_read_tools_and_maps_each_outcome() -> (
    None
):
    # An empty DATABASE_URL stops the server's own .env loading from supplying the real one.
    env = {"RISINGWAVE_PORT": "1", "OTEL_EXPORTER": "none", "DATABASE_URL": ""}
    params = stdio_parameters(env)
    assert params.command == sys.executable and params.args == ["-m", "finsentry.mcp.server"]
    async with connect_read_tools(params, call_timeout_s=60.0) as tools:
        adapter = ReadOnlyAdapter(tools)
        drift = await adapter.call("get_drift_report", "q1")
        offline = await adapter.call("get_failing_traces", "q2", failure_type="blocked")
        no_store = await adapter.call("list_red_team_executions", "q3", limit=5)
        invalid = await adapter.call("search_traces", "q4", limit=0)

    assert drift.status in ("ok", "empty")  # reads files; either is a fact about the platform
    assert offline.status == "unavailable"
    assert no_store.status == "unavailable"
    assert invalid.status == "rejected"
    for result in (offline, no_store, invalid):
        _no_evidence(result)
