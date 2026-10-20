"""
The investigation timeline: what the loop did, in order, as typed events.

The loop emits an event when it runs a query, plans, assesses its ledger and stops. Each one
records what the code decided and why, from values the loop already holds: the query and its
tool outcome, the hypotheses a plan proposed, how each prediction came out and which queries
judged it, the review's decision, and the stopping reason. Nothing here is a model's reasoning
text. A planner's hypotheses and predictions are structured fields it was asked for.

EventRecorder keeps events in order in memory and hands each one to an optional async sink as it
happens, so a store can persist progress while the investigation is still running. emit() is
synchronous and never blocks the loop. A sink failure is logged and never stops the run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finsentry.events.trace_api import TraceDetailResponse, TraceListResponse
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import (
    Confidence,
    EvidenceRef,
    Hypothesis,
    HypothesisStatus,
    ProposedVerification,
    StoppingReason,
    Subsystem,
    ToolName,
    ToolStatus,
)
from finsentry.investigator.ledger import Assessment, Review
from finsentry.investigator.planning import ValidatedPlan
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import GetFailingTracesResult, GuardrailDecisionSnapshot
from finsentry.redteam.records import ExecutionList, ExecutionRecord

log = logging.getLogger(__name__)

Fact = str | int | float | bool | None
# A handful of facts a tool returned about one record, kept so the page can say what a cited
# record was when it was read. The record itself stays where the platform stores it.
RecordFacts = dict[str, Fact]


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QueryRun(_Event):
    """One tool call and what came back. separates names the hypotheses it was chosen to tell
    apart, and is empty for the opening query and for a listing a sample is taken from."""

    kind: Literal["query"] = "query"
    query_id: str
    tool: ToolName
    args: dict[str, object]
    status: ToolStatus
    error: str | None = None
    separates: list[str] = Field(default_factory=list)
    retry_justification: str | None = None
    empty_unverified: bool = False
    elapsed_s: float
    records: dict[str, RecordFacts] = Field(default_factory=dict)


class PlannedPrediction(_Event):
    tool: ToolName
    signal: str | None
    expect: bool
    subject: str | None
    description: str
    query_key: str | None


class PlannedHypothesis(_Event):
    hypothesis_id: str
    subsystem: Subsystem
    symptom: str
    statement: str
    predictions: list[PlannedPrediction]


class PlanMade(_Event):
    """A planning round that produced a usable plan, after validation dropped what the tool
    surface does not support."""

    kind: Literal["plan"] = "plan"
    round: int
    planner: str
    hypotheses: list[PlannedHypothesis]
    queries_kept: int
    notes: list[str] = Field(default_factory=list)
    proposed_verification: ProposedVerification | None = None


class PlanFailed(_Event):
    kind: Literal["plan_failed"] = "plan_failed"
    round: int
    attempt: int
    error: str


class PredictionResult(_Event):
    tool: str
    signal: str
    expect: bool
    subject: str | None
    description: str
    state: Literal["met", "unmet", "unknown"]
    detail: str
    # The executed queries whose results judged this prediction, and no others.
    query_ids: list[str]
    restates_trigger: bool


class HypothesisAssessment(_Event):
    hypothesis_id: str
    subsystem: Subsystem
    symptom: str
    statement: str
    status: HypothesisStatus
    supporting: list[EvidenceRef]
    contradicting: list[EvidenceRef]
    predictions: list[PredictionResult]
    # Predictions set aside because their records cannot bear on this hypothesis's subsystem.
    set_aside: list[str] = Field(default_factory=list)


class Assessed(_Event):
    """The ledger after the results so far, and the review's decision on what to do next."""

    kind: Literal["assessment"] = "assessment"
    round: int
    decision: Literal["diagnose", "abstain", "continue"]
    hypotheses: list[HypothesisAssessment]
    leaders: list[str] = Field(default_factory=list)
    confidence: dict[str, Confidence] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class Stopped(_Event):
    kind: Literal["stopped"] = "stopped"
    stopping_reason: StoppingReason
    outcome: Literal["diagnosis", "abstention"]
    why: str


TimelineEvent = Annotated[
    QueryRun | PlanMade | PlanFailed | Assessed | Stopped, Field(discriminator="kind")
]


class TimelineEntry(BaseModel):
    """An event with its place in the sequence. at is when it was recorded, elapsed_s is the
    investigation's own clock."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=1)
    at: AwareDatetime
    elapsed_s: float
    event: TimelineEvent


Sink = Callable[[TimelineEntry], Awaitable[None]]


class EventRecorder:
    def __init__(self, sink: Sink | None = None) -> None:
        self.entries: list[TimelineEntry] = []
        self._sink = sink
        self._pending: set[asyncio.Task[None]] = set()

    def emit(self, event: TimelineEvent, elapsed_s: float) -> None:
        entry = TimelineEntry(
            seq=len(self.entries) + 1, at=datetime.now(UTC), elapsed_s=elapsed_s, event=event
        )
        self.entries.append(entry)
        if self._sink is not None:
            task = asyncio.ensure_future(self._deliver(entry))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def _deliver(self, entry: TimelineEntry) -> None:
        assert self._sink is not None
        try:
            await self._sink(entry)
        except Exception:
            log.warning("timeline event %s was not stored", entry.seq, exc_info=True)

    async def flush(self) -> None:
        """Wait for every event handed to the sink so far."""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


# Facts about the records a result returned.


def _key(ref_kind: str, record_id: str) -> str:
    return f"{ref_kind}:{record_id}"


def _execution(e: ExecutionRecord) -> RecordFacts:
    return {
        "scenario_id": e.scenario_id,
        "target_layer": e.target_layer,
        "outcome": e.outcome,
        "expected": e.expected.outcome,
        "expectation": e.expectation,
        "started_at": e.started_at.isoformat() if e.started_at else None,
    }


def describe_records(result: ToolResult) -> dict[str, RecordFacts]:
    """What the tool said about each record it returned, keyed 'kind:record_id'. Pure."""
    p = result.payload
    found: dict[str, RecordFacts] = {}
    if isinstance(p, GetFailingTracesResult):
        for t in p.traces:
            found[_key("trace", t.app_trace_id)] = {
                "classification": t.classification,
                "ticker": t.ticker,
                "endpoint": t.endpoint,
                "block_rail": t.block_rail,
                "error_kind": t.error_kind,
                "at": t.timestamp_utc,
            }
    elif isinstance(p, TraceListResponse):
        for item in p.traces:
            found[_key("trace", item.app_trace_id)] = {
                "rag_status": item.rag_status,
                "ticker": item.ticker,
                "judge_state": item.judge_state,
                "at": item.timestamp_utc.isoformat(),
            }
    elif isinstance(p, TraceDetailResponse) and p.found:
        flash = p.flash.faithfulness_score if p.flash else None
        evidence = p.frontier.evidence
        found[_key("trace", p.app_trace_id)] = {
            "rag_status": p.rag_status,
            "ticker": p.ticker,
            "block_rail": p.block_rail,
            "judge_state": p.judge_state,
            "chunks": ", ".join(p.retrieved_chunk_ids[:6]),
            "flash_faithfulness": flash,
            "frontier_faithfulness": evidence.faithfulness_score if evidence else None,
        }
    elif isinstance(p, GuardrailDecisionSnapshot) and p.found:
        found[_key("guardrail_decision", p.app_trace_id)] = {
            "status": p.status,
            "input_rail_status": p.input_rail_status,
            "block_rail": p.block_rail,
        }
    elif isinstance(p, GetJudgeScoresResult) and p.count:
        found[_key("judge_scores", p.app_trace_id)] = {
            "verdicts": p.count,
            "statuses": ", ".join(sorted({v.status for v in p.verdicts})),
        }
    elif isinstance(p, SearchPromptInjectionsResult):
        for event in p.direct:
            found[_key("injection_event", event.app_trace_id)] = {
                "block_rail": event.block_rail,
                "endpoint": event.endpoint,
                "at": event.timestamp_utc,
            }
    elif isinstance(p, GetDriftReportResult):
        reading = p.last_health_reading
        found[_key("drift_report", p.judge_id)] = {
            "state": reading.state if reading else None,
            "kappa": reading.kappa if reading else None,
            "transitions": len(p.transition_history),
        }
    elif isinstance(p, ExecutionList):
        for record in p.executions:
            found[_key("red_team_execution", record.execution_id)] = _execution(record)
    elif isinstance(p, RedTeamExecutionResult) and p.execution is not None:
        found[_key("red_team_execution", p.execution.execution_id)] = _execution(p.execution)
    return found


# Events from the loop's own values.


def plan_event(round_no: int, planner: str, plan: ValidatedPlan) -> PlanMade:
    return PlanMade(
        round=round_no,
        planner=planner,
        hypotheses=[
            PlannedHypothesis(
                hypothesis_id=h.hypothesis_id,
                subsystem=h.subsystem,
                symptom=h.symptom,
                statement=h.statement,
                predictions=[
                    PlannedPrediction(
                        tool=p.tool,
                        signal=p.signal,
                        expect=p.expect,
                        subject=p.subject,
                        description=p.description,
                        query_key=p.query_key,
                    )
                    for p in h.predicted_observations
                ],
            )
            for h in plan.hypotheses
        ],
        queries_kept=len(plan.queries),
        notes=list(plan.notes),
        proposed_verification=plan.verification,
    )


def assessed_event(
    round_no: int,
    ledger: list[Hypothesis],
    assessments: dict[str, Assessment],
    review: Review,
) -> Assessed:
    return Assessed(
        round=round_no,
        decision=review.decision,
        hypotheses=[
            HypothesisAssessment(
                hypothesis_id=h.hypothesis_id,
                subsystem=h.subsystem,
                symptom=h.symptom,
                statement=h.statement,
                status=h.status,
                supporting=list(h.supporting),
                contradicting=list(h.contradicting),
                predictions=[
                    PredictionResult(
                        tool=o.tool,
                        signal=o.signal,
                        expect=o.expect,
                        subject=o.subject,
                        description=o.description,
                        state=o.state,
                        detail=o.detail,
                        query_ids=list(o.query_ids),
                        restates_trigger=o.restates_trigger,
                    )
                    for o in assessments[h.hypothesis_id].outcomes
                ],
                set_aside=list(assessments[h.hypothesis_id].rejected),
            )
            for h in ledger
        ],
        leaders=list(review.leaders),
        confidence=dict(review.confidence),
        notes=list(review.notes),
        unresolved=list(review.unresolved),
    )
