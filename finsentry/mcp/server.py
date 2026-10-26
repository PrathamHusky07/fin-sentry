"""
MCP server wiring: instantiate MCPServer, register the nine read-only
tools, open/close the shared RisingWave pool via lifespan, run on stdio.

Tool logic lives in finsentry/mcp/tools/*.py; this module is registration
and process entrypoint only (python -m finsentry.mcp.server).

OpenTelemetry: the installed mcp SDK (2.3.0) ships `OpenTelemetryMiddleware`
on by default for every server (mcp/server/lowlevel/server.py) -- every
tools/call is already wrapped in a span carrying the tool name, outcome, and
latency, satisfying the July 2026 MCP spec's OTel requirement with no
per-tool span code here. configure_tracer_provider() (the same primitive
finsentry/gateway/main.py uses, driven by the same OTEL_EXPORTER env var) is
called once at startup so those spans export through the project's existing
OTel setup -- not a second config.

run_red_team_scenario is deliberately NOT registered. The Red Team tools here only read
stored executions. Whether an agent may start a run is a Day 11 decision.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal, cast

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from finsentry.mcp.state import dao
from finsentry.mcp.tools.drift import get_drift_report
from finsentry.mcp.tools.injections import search_prompt_injections
from finsentry.mcp.tools.judges import get_judge_scores
from finsentry.mcp.tools.redteam import get_red_team_execution, list_red_team_executions
from finsentry.mcp.tools.trace_evidence import get_trace_detail, search_traces
from finsentry.mcp.tools.traces import explain_guardrail_decision, get_failing_traces
from finsentry.observability.tracing import configure_tracer_provider

_INSTRUCTIONS = (
    "FinSentry operational investigation interface. Use these tools to "
    "investigate incidents: what's failing, why a request was blocked, "
    "what the judges scored, whether a prompt-injection pattern is present, "
    "whether the evaluator is drifting, and what the Red Team Console found. "
    "Every tool reads real persisted platform state and none of them writes. "
    "Nothing here is synthetic or mocked. get_drift_report "
    "reports the last-persisted monitoring snapshot, not a live feed."
)


@asynccontextmanager
async def _lifespan(_server: MCPServer[None]) -> AsyncGenerator[None]:
    await dao.open()
    yield
    await dao.close()


def build_server() -> MCPServer[None]:
    configure_tracer_provider(
        cast(Literal["console", "otlp", "none"], os.getenv("OTEL_EXPORTER", "none"))
    )
    server: MCPServer[None] = MCPServer(
        name="finsentry-ops",
        version="0.1.0",
        instructions=_INSTRUCTIONS,
        lifespan=_lifespan,
    )
    # Every tool only reads. The hint lets a client, and a test, tell that without reading code.
    for tool in (
        get_failing_traces,
        explain_guardrail_decision,
        get_judge_scores,
        search_prompt_injections,
        get_drift_report,
        search_traces,
        get_trace_detail,
        list_red_team_executions,
        get_red_team_execution,
    ):
        server.add_tool(tool, annotations=ToolAnnotations(read_only_hint=True))
    return server


server = build_server()


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
