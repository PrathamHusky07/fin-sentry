"""
The nine read-only MCP tools as a typed interface.

Every method mirrors the signature and return type of the function registered in
finsentry/mcp/server.py, copied from the code and not redesigned. tests/investigator/
test_tool_contract.py compares each method with the real function using resolved type hints
and defaults, so a change to a tool's parameters or result type fails that test until this
file follows.

This is an interface only. Day 11.0 does not connect it to a running MCP server. The
adapter in adapter.py accepts any object that satisfies it: a fixture world in the eval
harness today, a client of the real server when the investigation loop is built.
"""

from __future__ import annotations

import hashlib
import inspect
from typing import Protocol

from finsentry.events.trace_api import JudgeState, TraceDetailResponse, TraceListResponse
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


class McpReadTools(Protocol):
    async def get_failing_traces(
        self,
        time_window_minutes: int = 60,
        endpoint: str | None = None,
        failure_type: FailureType = "any",
        limit: int = 50,
        score_below: float | None = None,
    ) -> GetFailingTracesResult: ...

    async def explain_guardrail_decision(self, app_trace_id: str) -> GuardrailDecisionSnapshot: ...

    async def get_judge_scores(self, app_trace_id: str) -> GetJudgeScoresResult: ...

    async def search_prompt_injections(
        self, time_window_minutes: int = 60, limit: int = 50
    ) -> SearchPromptInjectionsResult: ...

    async def get_drift_report(self) -> GetDriftReportResult: ...

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
    ) -> TraceListResponse: ...

    async def get_trace_detail(self, app_trace_id: str) -> TraceDetailResponse: ...

    async def list_red_team_executions(
        self,
        limit: int = 20,
        offset: int = 0,
        category: Category | None = None,
        outcome: Outcome | None = None,
        scenario_id: str | None = None,
        run_id: str | None = None,
    ) -> ExecutionList: ...

    async def get_red_team_execution(self, execution_id: str) -> RedTeamExecutionResult: ...


def _contract_version() -> str:
    """A short hash of every method signature, so a recorded run names the tool surface it
    ran against."""
    lines = [
        f"{name}{inspect.signature(fn)}"
        for name, fn in sorted(vars(McpReadTools).items())
        if inspect.iscoroutinefunction(fn)
    ]
    return "mcp-read-9@" + hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


TOOL_CONTRACT_VERSION = _contract_version()
