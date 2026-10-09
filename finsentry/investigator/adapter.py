"""
Read-only adapter over the nine MCP tools.

It does two jobs. It refuses to call anything that is not one of the nine named read tools,
and it turns each tool's result into a status that never confuses "the tool could not run"
with "the tool ran and found nothing".

How each tool signals unavailability, from the code in finsentry/mcp/tools:

- get_failing_traces, explain_guardrail_decision, get_judge_scores and
  search_prompt_injections read through fetch_all/fetch_one, which return [] or None when
  RisingWave is offline. They set risingwave_connected=False in that case, and that flag is
  the only signal. An empty list with the flag False is unavailable, not empty.
- search_traces and get_trace_detail raise when RisingWave fails, and the dashboard
  response carries the same flag. A raise is unavailable.
- the Red Team tools raise ValueError("DATABASE_URL is not configured ...") when the store is
  unreachable. That is unavailable. Their other ValueErrors (limit, offset, a malformed UUID)
  are a rejected call.
- get_drift_report reads files. A missing health reading is empty, because the file is the
  source of truth and its absence is a fact about the platform.

Known gap, not fixed here: a SQL error on a connected pool returns [] with
risingwave_connected=True through the four fetch_all tools (the DAO keeps that in
last_query_failed, which no tool result exposes). The adapter cannot tell that from empty.
It is listed in KNOWN_TOOL_GAPS so every investigation starts with it declared.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from finsentry.events.trace_api import TraceDetailResponse, TraceListResponse
from finsentry.investigator.contracts import (
    TOOL_NAMES,
    DataGap,
    EvidenceKind,
    EvidenceRef,
    ToolName,
    ToolStatus,
)
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import GetFailingTracesResult, GuardrailDecisionSnapshot
from finsentry.redteam.records import ExecutionList

KNOWN_TOOL_GAPS: tuple[DataGap, ...] = (
    DataGap(
        source="get_failing_traces, explain_guardrail_decision, get_judge_scores, "
        "search_prompt_injections",
        kind="ambiguous",
        detail="A failed SQL query on a connected pool returns an empty result with "
        "risingwave_connected true, so it reads as no rows.",
    ),
    DataGap(
        source="search_prompt_injections",
        kind="not_persisted",
        detail="Indirect (retrieval-rail) injection drops are only logged, never persisted, "
        "so only direct input-rail blocks can be counted.",
    ),
    DataGap(
        source="get_trace_detail",
        kind="withheld",
        detail="answer, error_detail, citation quotes and the frontier rubric_reasoning are "
        "withheld, and queries over 500 characters are cut.",
    ),
    DataGap(
        source="get_drift_report",
        kind="snapshot_only",
        detail="Reports the last persisted canary reading, not a live monitor.",
    ),
    DataGap(
        source="search_traces",
        kind="ambiguous",
        detail="disagreement=False includes traces the two judge tiers never both scored, "
        "so it does not mean the tiers agreed.",
    ),
)


_STORE_NOT_CONFIGURED = "is not configured"


@dataclass(frozen=True)
class ToolResult:
    """One call's outcome. payload is the tool's own typed result, None when the call raised."""

    query_id: str
    tool: ToolName
    args: dict[str, object]
    status: ToolStatus
    evidence: list[EvidenceRef]
    payload: object | None
    error: str | None
    elapsed_s: float


def _refs(query_id: str, kind: EvidenceKind, ids: list[str]) -> list[EvidenceRef]:
    refs = [EvidenceRef(kind="query_result", record_id=query_id)]
    refs += [EvidenceRef(kind=kind, record_id=i) for i in dict.fromkeys(ids)]
    return refs


def interpret(
    tool: ToolName, payload: object, query_id: str
) -> tuple[ToolStatus, list[EvidenceRef], str | None]:
    """Status, citable evidence and an error note for one successful call. Pure."""
    offline = "RisingWave reported offline (risingwave_connected is false)"
    match payload:
        case GetFailingTracesResult(risingwave_connected=False):
            return "unavailable", [], offline
        case GetFailingTracesResult(traces=[]):
            return "empty", _refs(query_id, "trace", []), None
        case GetFailingTracesResult(traces=traces):
            return "ok", _refs(query_id, "trace", [t.app_trace_id for t in traces]), None
        case GuardrailDecisionSnapshot(found=False, risingwave_connected=False):
            return "unavailable", [], offline
        case GuardrailDecisionSnapshot(found=False):
            return "empty", _refs(query_id, "guardrail_decision", []), None
        case GuardrailDecisionSnapshot(app_trace_id=trace_id):
            return "ok", _refs(query_id, "guardrail_decision", [trace_id]), None
        case GetJudgeScoresResult(risingwave_connected=False):
            return "unavailable", [], offline
        case GetJudgeScoresResult(count=0):
            return "empty", _refs(query_id, "judge_scores", []), None
        case GetJudgeScoresResult(app_trace_id=trace_id):
            return "ok", _refs(query_id, "judge_scores", [trace_id]), None
        case SearchPromptInjectionsResult(risingwave_connected=False):
            return "unavailable", [], offline
        case SearchPromptInjectionsResult(direct=[]):
            return "empty", _refs(query_id, "injection_event", []), None
        case SearchPromptInjectionsResult(direct=events):
            return "ok", _refs(query_id, "injection_event", [e.app_trace_id for e in events]), None
        case GetDriftReportResult(last_health_reading=None):
            return "empty", _refs(query_id, "drift_report", []), None
        case GetDriftReportResult(judge_id=judge_id):
            return "ok", _refs(query_id, "drift_report", [judge_id]), None
        case TraceListResponse(risingwave_connected=False):
            return "unavailable", [], offline
        case TraceListResponse(traces=[]):
            return "empty", _refs(query_id, "trace", []), None
        case TraceListResponse(traces=traces):
            return "ok", _refs(query_id, "trace", [t.app_trace_id for t in traces]), None
        case TraceDetailResponse(found=False, risingwave_connected=False):
            return "unavailable", [], offline
        case TraceDetailResponse(found=False):
            return "empty", _refs(query_id, "trace", []), None
        case TraceDetailResponse(app_trace_id=trace_id):
            return "ok", _refs(query_id, "trace", [trace_id]), None
        case ExecutionList(executions=[]):
            return "empty", _refs(query_id, "red_team_execution", []), None
        case ExecutionList(executions=executions):
            ids = [e.execution_id for e in executions]
            return "ok", _refs(query_id, "red_team_execution", ids), None
        case RedTeamExecutionResult(found=False):
            return "empty", _refs(query_id, "red_team_execution", []), None
        case RedTeamExecutionResult(execution=execution) if execution is not None:
            return "ok", _refs(query_id, "red_team_execution", [execution.execution_id]), None
    return "unavailable", [], f"{tool} returned an unrecognised result type"


class ReadOnlyAdapter:
    """Calls the nine read tools and nothing else. It holds no write path and no other
    attribute of the tool object is reachable through it."""

    def __init__(self, tools: McpReadTools) -> None:
        self._tools = tools

    async def call(self, tool: str, query_id: str, **args: Any) -> ToolResult:
        if tool not in TOOL_NAMES:
            raise ValueError(f"{tool!r} is not one of the nine read-only investigation tools")
        name: ToolName = tool
        started = time.monotonic()
        try:
            payload = await getattr(self._tools, name)(**args)
        except ValueError as exc:
            # The Red Team tools raise ValueError for an unset DATABASE_URL, which is an
            # unreachable store and not a bad argument.
            status: ToolStatus = "unavailable" if _STORE_NOT_CONFIGURED in str(exc) else "rejected"
            return self._failure(query_id, name, args, status, exc, started)
        except Exception as exc:
            return self._failure(query_id, name, args, "unavailable", exc, started)
        status, evidence, error = interpret(name, payload, query_id)
        return ToolResult(
            query_id, name, dict(args), status, evidence, payload, error, time.monotonic() - started
        )

    @staticmethod
    def _failure(
        query_id: str,
        tool: ToolName,
        args: dict[str, Any],
        status: ToolStatus,
        exc: Exception,
        started: float,
    ) -> ToolResult:
        error = f"{type(exc).__name__}: {exc}"
        return ToolResult(
            query_id, tool, dict(args), status, [], None, error, time.monotonic() - started
        )
