"""
A fixture world: an in-memory implementation of McpReadTools over controlled data.

It returns the platform's own result types and applies the same filters and limit checks the
real tools do, so an investigator written against the interface cannot tell it from the
server except by what is in the data. Nothing here touches a database, a file, a network or a
model. A tool listed in `unavailable` fails the way the real one does when its source is
down: the four RisingWave-backed list tools return an empty result with
risingwave_connected false, and the rest raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from finsentry.events.trace_api import (
    JudgeState,
    TraceDetailResponse,
    TraceListItem,
    TraceListResponse,
)
from finsentry.investigator import fixtures as fx
from finsentry.investigator.contracts import ToolName
from finsentry.mcp._util import validate_limit
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import DirectInjectionEvent, SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult, JudgeVerdict
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import (
    FailingTrace,
    FailureType,
    GetFailingTracesResult,
    GuardrailDecisionSnapshot,
)
from finsentry.redteam.models import Category, Outcome
from finsentry.redteam.records import ExecutionList, ExecutionRecord

_JUDGE_CLASSES = ("judge_skipped", "judge_pipeline_failure")
_MAX_PAGE = 100


@dataclass(frozen=True)
class WorldData:
    failing: tuple[FailingTrace, ...] = ()
    decisions: dict[str, GuardrailDecisionSnapshot] = field(default_factory=dict)
    verdicts: dict[str, tuple[JudgeVerdict, ...]] = field(default_factory=dict)
    injections: tuple[DirectInjectionEvent, ...] = ()
    drift: GetDriftReportResult = field(default_factory=fx.drift_report)
    trace_items: tuple[TraceListItem, ...] = ()
    trace_details: dict[str, TraceDetailResponse] = field(default_factory=dict)
    disagreeing: frozenset[str] = frozenset()
    executions: tuple[ExecutionRecord, ...] = ()
    unavailable: frozenset[ToolName] = frozenset()


def _minutes_ago(iso: str | None) -> float:
    if iso is None:
        return 0.0
    return (fx.ANCHOR - datetime.fromisoformat(iso)).total_seconds() / 60


class FixtureWorld:
    def __init__(self, data: WorldData) -> None:
        self._d = data
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _log(self, name: str, **args: object) -> bool:
        """Record the call and say whether this tool's source is down."""
        self.calls.append((name, args))
        return name in self._d.unavailable

    async def get_failing_traces(
        self,
        time_window_minutes: int = 60,
        endpoint: str | None = None,
        failure_type: FailureType = "any",
        limit: int = 50,
        score_below: float | None = None,
    ) -> GetFailingTracesResult:
        down = self._log("get_failing_traces", failure_type=failure_type, limit=limit)
        validate_limit(limit)
        if down:
            return fx.failing_traces_result([], connected=False)
        wanted = {
            "blocked": ("guardrail_blocked",),
            "error": ("rag_system_error",),
            "judge_failed": _JUDGE_CLASSES,
            "any": ("guardrail_blocked", "rag_system_error", *_JUDGE_CLASSES),
        }[failure_type]
        rows = [
            t
            for t in self._d.failing
            if t.classification in wanted
            and (endpoint is None or t.endpoint == endpoint)
            and _minutes_ago(t.timestamp_utc) <= time_window_minutes
        ]
        rows.sort(key=lambda t: t.timestamp_utc or "", reverse=True)
        return fx.failing_traces_result(rows[:limit])

    async def explain_guardrail_decision(self, app_trace_id: str) -> GuardrailDecisionSnapshot:
        if self._log("explain_guardrail_decision", app_trace_id=app_trace_id):
            return fx.guardrail_decision(app_trace_id, found=False, connected=False)
        found = self._d.decisions.get(app_trace_id)
        return found or fx.guardrail_decision(app_trace_id, found=False)

    async def get_judge_scores(self, app_trace_id: str) -> GetJudgeScoresResult:
        if self._log("get_judge_scores", app_trace_id=app_trace_id):
            return fx.judge_scores(app_trace_id, [], connected=False)
        return fx.judge_scores(app_trace_id, list(self._d.verdicts.get(app_trace_id, ())))

    async def search_prompt_injections(
        self, time_window_minutes: int = 60, limit: int = 50
    ) -> SearchPromptInjectionsResult:
        down = self._log("search_prompt_injections", limit=limit)
        validate_limit(limit)
        if down:
            return fx.injections_result([], window_minutes=time_window_minutes, connected=False)
        rows = [
            e for e in self._d.injections if _minutes_ago(e.timestamp_utc) <= time_window_minutes
        ]
        return fx.injections_result(rows[:limit], window_minutes=time_window_minutes)

    async def get_drift_report(self) -> GetDriftReportResult:
        if self._log("get_drift_report"):
            raise OSError("the canary artifact could not be read")
        return self._d.drift

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
        down = self._log("search_traces", limit=limit, ticker=ticker, disagreement=disagreement)
        validate_limit(limit, _MAX_PAGE)
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if down:
            raise RuntimeError("RisingWave is not connected")
        rows = [
            t
            for t in self._d.trace_items
            if (ticker is None or t.ticker == ticker)
            and (rag_status is None or t.rag_status == rag_status)
            and (
                query_contains is None
                or query_contains in t.query
                or query_contains in t.app_trace_id
            )
            and (judge_state is None or t.judge_state == judge_state)
            and (frontier_sampled is None or t.frontier_sampled == frontier_sampled)
            and (disagreement is None or (t.app_trace_id in self._d.disagreeing) == disagreement)
        ]
        page = rows[offset : offset + limit]
        more = offset + limit < len(rows)
        return TraceListResponse(
            traces=page, next_offset=offset + limit if more else None, risingwave_connected=True
        )

    async def get_trace_detail(self, app_trace_id: str) -> TraceDetailResponse:
        if self._log("get_trace_detail", app_trace_id=app_trace_id):
            raise RuntimeError("RisingWave is not connected")
        return self._d.trace_details.get(app_trace_id) or fx.missing_trace_detail(app_trace_id)

    async def list_red_team_executions(
        self,
        limit: int = 20,
        offset: int = 0,
        category: Category | None = None,
        outcome: Outcome | None = None,
        scenario_id: str | None = None,
        run_id: str | None = None,
    ) -> ExecutionList:
        down = self._log("list_red_team_executions", scenario_id=scenario_id, outcome=outcome)
        validate_limit(limit, _MAX_PAGE)
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")
        if down:
            raise ValueError("DATABASE_URL is not configured, so the red team store cannot be read")
        rows = [
            e
            for e in self._d.executions
            if (category is None or e.category == category)
            and (outcome is None or e.outcome == outcome)
            and (scenario_id is None or e.scenario_id == scenario_id)
            and (run_id is None or e.run_id == run_id)
        ]
        page = rows[offset : offset + limit]
        return ExecutionList(
            executions=page, next_offset=offset + limit if offset + limit < len(rows) else None
        )

    async def get_red_team_execution(self, execution_id: str) -> RedTeamExecutionResult:
        if self._log("get_red_team_execution", execution_id=execution_id):
            raise ValueError("DATABASE_URL is not configured, so the red team store cannot be read")
        match = next((e for e in self._d.executions if e.execution_id == execution_id), None)
        return RedTeamExecutionResult(found=match is not None, execution=match)
