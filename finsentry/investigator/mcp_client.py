"""
The official MCP Python SDK client, behind the typed McpReadTools interface.

connect_read_tools opens a session to the real server (python -m finsentry.mcp.server over
stdio, or any MCPServer handed in for tests), lists its tools and refuses to continue unless
the surface is exactly the nine read-only tools: no extra tool, none missing, each annotated
read-only and not destructive. Past that check the only way to reach a tool is one of the
nine methods below, and the adapter above this class refuses any other name as well.

Errors map the way the adapter expects. A call that fails argument validation, before it is
sent or on the server, raises ValueError and reads as rejected. Anything else the server or
the transport reports raises ToolExecutionError, and reads as unavailable. See tool_args.py
for why the split is made before the call.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp_types import Tool
from pydantic import TypeAdapter

from finsentry.events.trace_api import JudgeState, TraceDetailResponse, TraceListResponse
from finsentry.investigator.contracts import TOOL_NAMES
from finsentry.investigator.tool_args import validate_tool_args
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import (
    FailureType,
    GetFailingTracesResult,
    GuardrailDecisionSnapshot,
)
from finsentry.redteam.models import Category, Outcome
from finsentry.redteam.records import ExecutionList

T = TypeVar("T")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The server reads its sources from the environment, and the SDK passes a child process only
# a short default set, so these are forwarded by name. Nothing else is.
FORWARDED_ENV = ("DATABASE_URL", "OTEL_EXPORTER")
FORWARDED_ENV_PREFIXES = ("RISINGWAVE_",)


class UnsafeToolSurfaceError(RuntimeError):
    """The server offers something other than the nine read-only tools."""


class ToolExecutionError(RuntimeError):
    """A call the server or the transport could not complete."""


def check_tool_surface(tools: list[Tool]) -> None:
    names = [t.name for t in tools]
    extra, missing = sorted(set(names) - set(TOOL_NAMES)), sorted(set(TOOL_NAMES) - set(names))
    if extra or missing or len(names) != len(set(names)):
        raise UnsafeToolSurfaceError(f"tool surface differs: unexpected {extra}, missing {missing}")
    for tool in tools:
        hints = tool.annotations
        if hints is None or hints.read_only_hint is not True or hints.destructive_hint:
            raise UnsafeToolSurfaceError(f"{tool.name} is not annotated read-only")


def stdio_parameters(env: Mapping[str, str] | None = None) -> StdioServerParameters:
    source = os.environ if env is None else env
    forwarded = {
        k: v
        for k, v in source.items()
        if k in FORWARDED_ENV or k.startswith(FORWARDED_ENV_PREFIXES)
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "finsentry.mcp.server"],
        env={"OTEL_EXPORTER": "none", **forwarded},
        cwd=PROJECT_ROOT,
    )


def _first_text(result: Any) -> str:
    return next((c.text for c in result.content if hasattr(c, "text")), "no detail")


class McpToolClient:
    """McpReadTools over a live MCP session. Build one with connect_read_tools.

    failed_query_raises is True because the four row-reading tools raise when a query fails on
    a live pool, which reaches this client as a failed call. The adapter therefore trusts an
    empty result from them as no rows. test_stdio_failed_query.py proves it over the real
    stdio server."""

    failed_query_raises = True

    def __init__(self, client: Client, *, call_timeout_s: float = 30.0) -> None:
        self._client = client
        self._timeout = call_timeout_s

    async def _call(self, name: str, args: Mapping[str, object], result_type: type[T]) -> T:
        problems = validate_tool_args(name, args)
        if problems:
            raise ValueError(f"{name} rejected the arguments: {'; '.join(problems)}")
        try:
            result = await self._client.call_tool(
                name, dict(args), read_timeout_seconds=self._timeout
            )
        except Exception as exc:
            raise ToolExecutionError(f"{name} could not be called: {exc}") from exc
        if result.is_error:
            text = _first_text(result)
            if "validation error" in text or "rejected arguments" in text:
                raise ValueError(f"{name} rejected the arguments: {text}")
            raise ToolExecutionError(f"{name} failed on the server: {text}")
        if result.structured_content is None:
            raise ToolExecutionError(f"{name} returned no structured content")
        return TypeAdapter(result_type).validate_python(result.structured_content)

    async def get_failing_traces(
        self,
        time_window_minutes: int = 60,
        endpoint: str | None = None,
        failure_type: FailureType = "any",
        limit: int = 50,
        score_below: float | None = None,
    ) -> GetFailingTracesResult:
        args = dict(
            time_window_minutes=time_window_minutes,
            endpoint=endpoint,
            failure_type=failure_type,
            limit=limit,
            score_below=score_below,
        )
        return await self._call("get_failing_traces", args, GetFailingTracesResult)

    async def explain_guardrail_decision(self, app_trace_id: str) -> GuardrailDecisionSnapshot:
        args = {"app_trace_id": app_trace_id}
        return await self._call("explain_guardrail_decision", args, GuardrailDecisionSnapshot)

    async def get_judge_scores(self, app_trace_id: str) -> GetJudgeScoresResult:
        return await self._call(
            "get_judge_scores", {"app_trace_id": app_trace_id}, GetJudgeScoresResult
        )

    async def search_prompt_injections(
        self, time_window_minutes: int = 60, limit: int = 50
    ) -> SearchPromptInjectionsResult:
        args = {"time_window_minutes": time_window_minutes, "limit": limit}
        return await self._call("search_prompt_injections", args, SearchPromptInjectionsResult)

    async def get_drift_report(self) -> GetDriftReportResult:
        return await self._call("get_drift_report", {}, GetDriftReportResult)

    async def search_traces(
        self,
        limit: int = 20,
        offset: int = 0,
        ticker: str | None = None,
        rag_status: str | None = None,
        query_contains: str | None = None,
        judge_state: JudgeState | None = None,
        frontier_sampled: bool | None = None,
        disagreement: bool | None = None,
    ) -> TraceListResponse:
        args = dict(
            limit=limit,
            offset=offset,
            ticker=ticker,
            rag_status=rag_status,
            query_contains=query_contains,
            judge_state=judge_state,
            frontier_sampled=frontier_sampled,
            disagreement=disagreement,
        )
        return await self._call("search_traces", args, TraceListResponse)

    async def get_trace_detail(self, app_trace_id: str) -> TraceDetailResponse:
        return await self._call(
            "get_trace_detail", {"app_trace_id": app_trace_id}, TraceDetailResponse
        )

    async def list_red_team_executions(
        self,
        limit: int = 20,
        offset: int = 0,
        category: Category | None = None,
        outcome: Outcome | None = None,
        scenario_id: str | None = None,
        run_id: str | None = None,
    ) -> ExecutionList:
        args = dict(
            limit=limit,
            offset=offset,
            category=category,
            outcome=outcome,
            scenario_id=scenario_id,
            run_id=run_id,
        )
        return await self._call("list_red_team_executions", args, ExecutionList)

    async def get_red_team_execution(self, execution_id: str) -> RedTeamExecutionResult:
        args = {"execution_id": execution_id}
        return await self._call("get_red_team_execution", args, RedTeamExecutionResult)


@asynccontextmanager
async def connect_read_tools(
    server: StdioServerParameters | MCPServer | None = None, *, call_timeout_s: float = 30.0
) -> AsyncIterator[McpToolClient]:
    """A session to the real server, checked to expose only the nine read-only tools."""
    refusal: UnsafeToolSurfaceError | None = None
    async with Client(server or stdio_parameters()) as client:
        try:
            check_tool_surface((await client.list_tools()).tools)
        except UnsafeToolSurfaceError as exc:
            refusal = exc  # raised after the session closes, so it is not wrapped by the SDK
        else:
            yield McpToolClient(client, call_timeout_s=call_timeout_s)
    if refusal is not None:
        raise refusal
