"""
Builders for the real result types of the nine MCP tools.

The eval harness and the tests need tool results with a known cause behind them. These
functions build the platform's own dataclasses and models (not look-alikes), with explicit
defaults, so a fixture can only drift from the real shape if the real type changes, and
then it fails to construct.

All timestamps hang off ANCHOR so a fixture is identical on every run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from finsentry.events.trace_api import (
    FlashJudgeView,
    FrontierEvidenceView,
    FrontierSectionView,
    JudgeState,
    TraceDetailResponse,
    TraceListItem,
)
from finsentry.mcp.tools.drift import (
    DriftPolicy,
    GetDriftReportResult,
    LastHealthReading,
    TransitionRecordSummary,
)
from finsentry.mcp.tools.injections import DirectInjectionEvent, SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult, JudgeVerdict
from finsentry.mcp.tools.traces import (
    FailingTrace,
    FailureClassification,
    GetFailingTracesResult,
    GuardrailDecisionSnapshot,
)
from finsentry.redteam.models import Category, Expected, Mode, Outcome, Rail
from finsentry.redteam.records import ExecutionRecord
from finsentry.reliability.health import DriftConfig

ANCHOR = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def at(minutes_ago: float) -> datetime:
    return ANCHOR - timedelta(minutes=minutes_ago)


def _iso(minutes_ago: float) -> str:
    return at(minutes_ago).isoformat()


def failing_trace(
    trace_id: str,
    classification: FailureClassification = "guardrail_blocked",
    *,
    minutes_ago: float = 10,
    ticker: str | None = "AAPL",
    endpoint: str | None = "/rag/query",
    block_reason: str | None = None,
    block_rail: str | None = None,
    error_kind: str | None = None,
    total_gemini_calls: int | None = None,
) -> FailingTrace:
    from_judge = classification in ("judge_skipped", "judge_pipeline_failure")
    return FailingTrace(
        app_trace_id=trace_id,
        source="judge_verdict" if from_judge else "rag_event",
        status="failed"
        if from_judge
        else ("error" if classification == "rag_system_error" else "blocked"),
        endpoint=endpoint,
        ticker=ticker,
        timestamp_utc=_iso(minutes_ago),
        classification=classification,
        block_reason=block_reason,
        block_rail=block_rail,
        error_kind=error_kind,
        total_gemini_calls=total_gemini_calls,
    )


def failing_traces_result(
    traces: list[FailingTrace], *, connected: bool = True
) -> GetFailingTracesResult:
    counts: dict[str, int] = {}
    for t in traces:
        if t.classification is not None:
            counts[t.classification] = counts.get(t.classification, 0) + 1
    return GetFailingTracesResult(
        traces=traces,
        classification_counts=counts,
        score_filter_match_count=0,
        unique_trace_count=len({t.app_trace_id for t in traces}),
        risingwave_connected=connected,
    )


def guardrail_decision(
    trace_id: str,
    *,
    found: bool = True,
    status: str = "blocked",
    input_rail_status: str = "passed",
    block_reason: str | None = None,
    block_rail: str | None = None,
    output_rails: dict[str, object] | None = None,
    connected: bool = True,
) -> GuardrailDecisionSnapshot:
    if not found:
        return GuardrailDecisionSnapshot(
            app_trace_id=trace_id, found=False, risingwave_connected=connected
        )
    return GuardrailDecisionSnapshot(
        app_trace_id=trace_id,
        found=True,
        status=status,
        endpoint="/rag/query",
        timestamp_utc=_iso(10),
        input_rail_status=input_rail_status,
        block_reason=block_reason,
        block_rail=block_rail,
        output_rail_trace_snapshot=dict(output_rails or {}),
        risingwave_connected=connected,
        note="persisted rail-decision snapshot, not a NeMo ExplainInfo trace",
    )


def judge_verdict(
    *,
    tier: Literal["flash", "frontier"] = "flash",
    status: str = "complete",
    faithfulness: float | None = 0.9,
    faithfulness_status: str | None = "complete",
    gemini_calls: int = 3,
) -> JudgeVerdict:
    return JudgeVerdict(
        judge_tier=tier,
        judge_model="gemini-2.5-flash" if tier == "flash" else "gemini-rubric",
        status=status,
        timestamp_utc=_iso(9),
        faithfulness_score=faithfulness,
        faithfulness_status=faithfulness_status,
        answer_relevance_score=0.9 if status == "complete" else None,
        answer_relevance_status="complete" if status == "complete" else "skipped_evaluator_error",
        context_relevance_score=0.9 if status == "complete" else None,
        context_relevance_status="complete" if status == "complete" else "skipped_evaluator_error",
        total_input_tokens=1200,
        total_output_tokens=200,
        total_thoughts_tokens=0,
        total_gemini_calls=gemini_calls,
        total_cost_usd=0.0,
        evaluation_latency_ms=800,
    )


def judge_scores(
    trace_id: str, verdicts: list[JudgeVerdict], *, connected: bool = True
) -> GetJudgeScoresResult:
    return GetJudgeScoresResult(
        app_trace_id=trace_id,
        verdicts=verdicts,
        count=len(verdicts),
        risingwave_connected=connected,
    )


def injection_event(trace_id: str, *, minutes_ago: float = 5) -> DirectInjectionEvent:
    return DirectInjectionEvent(
        app_trace_id=trace_id,
        endpoint="/rag/query",
        block_rail="check prompt injection",
        block_reason="prompt injection detected",
        timestamp_utc=_iso(minutes_ago),
    )


def injections_result(
    events: list[DirectInjectionEvent], *, window_minutes: int = 60, connected: bool = True
) -> SearchPromptInjectionsResult:
    counts = {"check prompt injection": len(events)} if events else {}
    return SearchPromptInjectionsResult(
        time_window_minutes=window_minutes,
        direct=events,
        direct_count_by_rail=counts,
        indirect=None,
        indirect_deferred_reason="indirect drops are logged but not persisted",
        risingwave_connected=connected,
    )


def drift_report(
    *,
    state: str | None = "healthy",
    kappa: float | None = 0.6,
    transitions: list[TransitionRecordSummary] | None = None,
) -> GetDriftReportResult:
    c = DriftConfig()
    policy = DriftPolicy(
        window_size=c.window_size,
        min_n=c.min_n,
        healthy_baseline_kappa=c.healthy_baseline_kappa,
        drift_entry_threshold=c.drift_entry_threshold,
        recovery_threshold=c.recovery_threshold,
        entry_consecutive_windows=c.entry_consecutive_windows,
        recovery_consecutive_windows=c.recovery_consecutive_windows,
    )
    reading = (
        None
        if state is None
        else LastHealthReading(
            state=state,
            kappa=kappa,
            window_n=c.window_size,
            committed_n=c.window_size,
            n_abstain=0,
            n_unavailable=0,
            state_as_of=_iso(30),
            source="docs/measurements/reliability/canary-live-smoke-d6p2.json",
        )
    )
    return GetDriftReportResult(
        judge_id="gemini-rubric",
        policy=policy,
        last_health_reading=reading,
        transition_history=transitions or [],
        note="reporting last-persisted state as of state_as_of; this is not a continuously "
        "running monitor",
    )


def trace_item(
    trace_id: str,
    *,
    minutes_ago: float = 10,
    ticker: str | None = "AAPL",
    rag_status: str = "success",
    block_reason: str | None = None,
    judge_state: JudgeState = "evaluated",
    frontier_sampled: bool = False,
) -> TraceListItem:
    return TraceListItem(
        app_trace_id=trace_id,
        timestamp_utc=at(minutes_ago),
        endpoint="/rag/query",
        ticker=ticker,
        query="What were net sales last fiscal year?",
        rag_status=rag_status,
        block_reason=block_reason,
        judge_state=judge_state,
        frontier_sampled=frontier_sampled,
    )


def trace_detail(
    trace_id: str,
    *,
    ticker: str | None = "AAPL",
    rag_status: str = "success",
    chunks: list[str] | None = None,
    block_reason: str | None = None,
    block_rail: str | None = None,
    error_kind: str | None = None,
    judge_state: JudgeState = "evaluated",
    flash_faithfulness: float | None = 0.9,
    frontier_faithfulness: float | None = None,
    contradicting_chunks: list[str] | None = None,
    connected: bool = True,
) -> TraceDetailResponse:
    never_judged = judge_state in ("blocked_before_evaluation", "never_evaluated")
    flash = (
        None
        if never_judged
        else FlashJudgeView(
            status="complete" if flash_faithfulness is not None else "failed",
            timestamp_utc=at(9),
            faithfulness_score=flash_faithfulness,
            faithfulness_status="complete"
            if flash_faithfulness is not None
            else "skipped_evaluator_error",
            answer_relevance_score=0.9,
            answer_relevance_status="complete",
            context_relevance_score=0.9,
            context_relevance_status="complete",
        )
    )
    if frontier_faithfulness is None:
        frontier = FrontierSectionView(sampled=False, evidence=None, note="not frontier-sampled")
    else:
        frontier = FrontierSectionView(
            sampled=True,
            evidence=FrontierEvidenceView(
                judge_id="gemini-rubric",
                faithfulness_score=frontier_faithfulness,
                rubric_reasoning=None,
                cited_chunks_supporting=[],
                cited_chunks_contradicting=contradicting_chunks or [],
                verdict="supported" if frontier_faithfulness >= 0.5 else "unsupported",
                evaluation_ts=at(8),
            ),
            note="real gemini-rubric result",
        )
    return TraceDetailResponse(
        app_trace_id=trace_id,
        found=True,
        rag_status=rag_status,
        endpoint="/rag/query",
        ticker=ticker,
        query="What were net sales last fiscal year?",
        answer=None,
        confidence=None,
        model_used=None,
        citations=[],
        retrieved_chunk_ids=chunks or [],
        block_reason=block_reason,
        block_rail=block_rail,
        error_kind=error_kind,
        error_detail=None,
        timestamp_utc=at(10),
        judge_state=judge_state,
        flash=flash,
        frontier=frontier,
        risingwave_connected=connected,
        note="persisted trace, answer withheld",
    )


def missing_trace_detail(trace_id: str, *, connected: bool = True) -> TraceDetailResponse:
    return TraceDetailResponse(
        app_trace_id=trace_id,
        found=False,
        rag_status=None,
        endpoint=None,
        ticker=None,
        query=None,
        answer=None,
        confidence=None,
        model_used=None,
        citations=[],
        retrieved_chunk_ids=[],
        block_reason=None,
        block_rail=None,
        error_kind=None,
        error_detail=None,
        timestamp_utc=None,
        judge_state="never_evaluated",
        flash=None,
        frontier=FrontierSectionView(sampled=False, evidence=None, note=""),
        risingwave_connected=connected,
        note="no matching rag_events row",
    )


def execution(
    execution_id: str,
    scenario_id: str,
    category: Category,
    *,
    outcome: Outcome,
    expected_caught_by: Rail | None,
    target_layer: str = "prompt-guard-2",
    mode: Mode = "deterministic",
    trace_ref: str | None = None,
    minutes_ago: float = 20,
) -> ExecutionRecord:
    """A finished execution. expected_caught_by None means the scenario expected a miss."""
    expected = (
        Expected(outcome="caught", layer=expected_caught_by, rationale="the layer is built for it")
        if expected_caught_by is not None
        else Expected(outcome="missed", known_gap=True, rationale="a documented gap")
    )
    matches = (outcome == "caught") == (expected_caught_by is not None)
    return ExecutionRecord(
        execution_id=execution_id,
        run_id="00000000-0000-0000-0000-000000000001",
        seq=0,
        scenario_id=scenario_id,
        scenario_version=1,
        category=category,
        target_layer=target_layer,
        mode=mode,
        expected=expected,
        state="finished",
        outcome=outcome,
        acting_layer=expected_caught_by if outcome == "caught" else None,
        acting_check=None,
        expectation="met" if matches else "not_met",
        reason=f"{outcome} as observed",
        evidence={},
        trace_ref=trace_ref,
        gemini_calls=0,
        cost_usd=0.0,
        started_at=at(minutes_ago),
        finished_at=at(minutes_ago - 0.1),
        duration_ms=100,
    )
