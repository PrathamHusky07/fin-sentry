"""
Typed contracts for the Day 9 trace-investigation routes: the Judge Panel
list, the trace drill-down, and the calibration-health panel. Shared
between the dashboard (which queries RisingWave and disk artifacts to build
these) and the gateway (which only ever sees the resulting JSON over
httpx) -- same Option C boundary as finsentry/events/metrics_snapshot.py.

judge_state is the five-state model confirmed against real persisted data
(see docs/build-log.md): a judge_verdicts row with status="complete" is
"evaluated"; status="partial" is "partially_evaluated" (some of the three
RAGAS metrics completed, others skipped for a judge-side reason); no
judge_verdicts row at all (a success rag_events row the async consumer
never produced a verdict for) is "never_evaluated".

A judge_verdicts row with status="failed" splits on the paired rag_events
row's status (Day 9 Session 2B -- Phase 0 found the two-state version of
this conflated two different things):

- rag_status != "success" (blocked/error): "blocked_before_evaluation" --
  there was nothing to judge, never a judge error.
- rag_status == "success": "judge_failed" -- the RAG request succeeded but
  FlashJudge.evaluate's complete_count==0 branch (finsentry/judges/
  flash_judge.py) means all three RAGAS metrics errored out or were
  skipped (a Gemini outage, a missing API key) on a request that had a
  real answer to judge. This is a judge-pipeline outage, not a guardrail
  decision -- surface it as an operational event, not a security block.

Never collapse these into fewer states.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

JudgeState = Literal[
    "evaluated",
    "partially_evaluated",
    "blocked_before_evaluation",
    "judge_failed",
    "never_evaluated",
]


class TraceListItem(BaseModel):
    app_trace_id: str
    timestamp_utc: datetime
    endpoint: str
    ticker: str | None
    query: str
    rag_status: str
    block_reason: str | None
    judge_state: JudgeState
    frontier_sampled: bool


class TraceListResponse(BaseModel):
    traces: list[TraceListItem]
    next_offset: int | None
    risingwave_connected: bool


class FlashJudgeView(BaseModel):
    """One judge_verdicts row's three RAGAS metrics, each score paired with
    its own status so a null score is never rendered without the reason it
    is null (see finsentry.events.trace_api module docstring)."""

    status: str
    timestamp_utc: datetime | None
    faithfulness_score: float | None
    faithfulness_status: str | None
    answer_relevance_score: float | None
    answer_relevance_status: str | None
    context_relevance_score: float | None
    context_relevance_status: str | None


class FrontierEvidenceView(BaseModel):
    """One real, non-stub gemini-rubric judge result. Never constructed for
    a stub-a/stub-b/test-judge entry or a null-evidence entry -- those are
    filtered out before this model is built (see dashboard _fetch_trace_detail)."""

    judge_id: Literal["gemini-rubric"]
    faithfulness_score: float | None
    rubric_reasoning: str | None
    cited_chunks_supporting: list[str]
    cited_chunks_contradicting: list[str]
    verdict: str
    evaluation_ts: datetime


class FrontierSectionView(BaseModel):
    """sampled=False means no rag_frontier_verdicts row exists for this
    trace at all (the ~90% case, per the deterministic 10% sampling hash).
    sampled=True with evidence=None means a row exists but carried no real,
    non-null-evidence gemini-rubric entry (e.g. stub-only fixture data, or
    a genuine orchestrator failure producing an empty per_judge_results).
    Never synthesize a unified multi-judge object from this."""

    sampled: bool
    evidence: FrontierEvidenceView | None
    note: str


class TraceDetailResponse(BaseModel):
    app_trace_id: str
    found: bool
    rag_status: str | None
    endpoint: str | None
    ticker: str | None
    query: str | None
    answer: str | None
    confidence: str | None
    model_used: str | None
    citations: list[dict[str, str]]
    retrieved_chunk_ids: list[str]
    block_reason: str | None
    block_rail: str | None
    error_kind: str | None
    error_detail: str | None
    timestamp_utc: datetime | None
    judge_state: JudgeState
    flash: FlashJudgeView | None
    frontier: FrontierSectionView
    risingwave_connected: bool
    note: str


class CalibrationHealthResponse(BaseModel):
    """Current position vs. the Day 6 DriftConfig thresholds -- a single
    point-in-time panel, never a trend chart (only one real historical
    kappa observation exists on disk)."""

    judge_id: str
    kappa: float | None
    state: str | None
    window_n: int | None
    min_n: int
    healthy_baseline_kappa: float
    drift_entry_threshold: float
    recovery_threshold: float
    position: Literal[
        "at_or_above_recovery", "between_thresholds", "at_or_below_entry", "insufficient_data"
    ]
    state_as_of: str | None
    note: str
