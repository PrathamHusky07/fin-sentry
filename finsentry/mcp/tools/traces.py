"""
get_failing_traces and explain_guardrail_decision: both read individual rows
from the rag_events RisingWave source (not an aggregate materialized view --
these tools need per-trace detail, not window summaries). get_failing_traces
also reads judge_verdicts for judge-pipeline failures, joined back to
rag_events for endpoint/ticker context.

Skip vs. failure classification (judge_verdict rows only). A judge_verdicts
row with status in (partial, failed) means fewer than 3 of the 3 RAGAS
metrics completed -- but *why* is not uniform. FlashJudge (finsentry/judges/
flash_judge.py) marks all three metrics "skipped_non_success" (no answer to
judge -- a blocked/errored request) or "skipped_no_key" (judge disabled)
*without ever calling Gemini*, so total_gemini_calls stays 0: there was
nothing to evaluate, which is a judge-skip, not a pipeline failure. A
"skipped_evaluator_error" status means the judge *did* call Gemini and the
evaluator itself raised -- a real pipeline failure. Both skip reasons already
collapse to total_gemini_calls=0 (nothing ran) vs. >0 (something ran and
failed), so that persisted field alone -- no new event field -- distinguishes
them: status in (partial, failed) with total_gemini_calls=0 is
"judge_skipped"; the same status with total_gemini_calls>0 is
"judge_pipeline_failure". rag_events rows classify directly from their own
status: "blocked" -> "guardrail_blocked", "error" -> "rag_system_error".

score_below is a separate, operator-supplied investigation filter, NOT a
failure classifier. It additionally returns status="complete" judge_verdicts
rows where answer_relevance_score or context_relevance_score falls below the
caller's chosen value. There is no calibrated platform threshold for either
dimension (unlike faithfulness, which gates generation at a Python default of
0.7 -- see finsentry/rails docs), so a score_below match is flagged via
matched_score_filter (which dimension, what actual score) and carries no
classification -- the same row is included or excluded purely by whatever
value the caller passes, which is exactly why it cannot be a failure verdict.
Faithfulness is excluded from this filter: the async Flash judge recomputes
faithfulness independently of the gate that already made the pass/fail call
for that response, so it is a noisy signal to re-threshold here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from finsentry.mcp._util import iso, validate_limit
from finsentry.mcp.state import dao

FailureType = Literal["blocked", "error", "judge_failed", "any"]

FailureClassification = Literal[
    "guardrail_blocked", "rag_system_error", "judge_skipped", "judge_pipeline_failure"
]

_RAG_EVENT_STATUSES: dict[str, list[str]] = {
    "blocked": ["blocked"],
    "error": ["error"],
    "any": ["blocked", "error"],
}
_RAG_EVENT_CLASSIFICATION: dict[str, FailureClassification] = {
    "blocked": "guardrail_blocked",
    "error": "rag_system_error",
}
_JUDGE_FAILURE_STATUSES = ["partial", "failed"]


@dataclass
class ScoreFilterMatch:
    dimension: Literal["answer_relevance", "context_relevance"]
    score: float
    threshold: float


@dataclass
class FailingTrace:
    app_trace_id: str
    source: Literal["rag_event", "judge_verdict"]
    status: str
    endpoint: str | None
    ticker: str | None
    timestamp_utc: str | None
    classification: FailureClassification | None = None
    block_reason: str | None = None
    block_rail: str | None = None
    error_kind: str | None = None
    error_detail: str | None = None
    total_gemini_calls: int | None = None
    matched_score_filter: list[ScoreFilterMatch] = field(default_factory=list)


@dataclass
class GetFailingTracesResult:
    traces: list[FailingTrace]
    classification_counts: dict[str, int]
    score_filter_match_count: int
    unique_trace_count: int
    risingwave_connected: bool


async def _fetch_rag_event_failures(
    time_window_minutes: int, endpoint: str | None, statuses: list[str], limit: int
) -> list[FailingTrace]:
    conditions = ["status = ANY(%s)", "timestamp_utc >= NOW() - (%s * INTERVAL '1 minute')"]
    params: list[Any] = [statuses, time_window_minutes]
    if endpoint is not None:
        conditions.append("endpoint = %s")
        params.append(endpoint)

    # LIMIT must be a const expression in RisingWave's streaming query
    # planner -- a bound %s parameter fails to prepare ("expects an integer
    # or expression that can be evaluated to an integer after LIMIT, but
    # found non-const expression"). limit is already int-typed by this
    # tool's own input schema, so inlining it is safe.
    rows = await dao.fetch_all(
        f"""
        SELECT app_trace_id, status, endpoint, ticker, timestamp_utc,
               block_reason, block_rail, error_kind, error_detail
        FROM rag_events
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp_utc DESC
        LIMIT {int(limit)}
        """,
        tuple(params),
    )
    return [
        FailingTrace(
            app_trace_id=r["app_trace_id"],
            source="rag_event",
            status=r["status"],
            endpoint=r["endpoint"],
            ticker=r["ticker"],
            timestamp_utc=iso(r["timestamp_utc"]),
            classification=_RAG_EVENT_CLASSIFICATION.get(r["status"]),
            block_reason=r["block_reason"],
            block_rail=r["block_rail"],
            error_kind=r["error_kind"],
            error_detail=r["error_detail"],
        )
        for r in rows
    ]


async def _fetch_judge_failures(
    time_window_minutes: int, endpoint: str | None, limit: int
) -> list[FailingTrace]:
    conditions = ["j.status = ANY(%s)", "j.timestamp_utc >= NOW() - (%s * INTERVAL '1 minute')"]
    params: list[Any] = [_JUDGE_FAILURE_STATUSES, time_window_minutes]
    if endpoint is not None:
        conditions.append("r.endpoint = %s")
        params.append(endpoint)

    rows = await dao.fetch_all(
        f"""
        SELECT j.app_trace_id, j.status, r.endpoint, r.ticker, j.timestamp_utc,
               j.total_gemini_calls
        FROM judge_verdicts j
        LEFT JOIN rag_events r ON r.app_trace_id = j.app_trace_id
        WHERE {" AND ".join(conditions)}
        ORDER BY j.timestamp_utc DESC
        LIMIT {int(limit)}
        """,
        tuple(params),
    )
    return [
        FailingTrace(
            app_trace_id=r["app_trace_id"],
            source="judge_verdict",
            status=r["status"],
            endpoint=r["endpoint"],
            ticker=r["ticker"],
            timestamp_utc=iso(r["timestamp_utc"]),
            classification=(
                "judge_skipped" if r["total_gemini_calls"] == 0 else "judge_pipeline_failure"
            ),
            total_gemini_calls=r["total_gemini_calls"],
        )
        for r in rows
    ]


async def _fetch_score_filtered_rows(
    time_window_minutes: int, endpoint: str | None, score_below: float, limit: int
) -> list[FailingTrace]:
    """Operator investigation filter, not a failure source: status='complete'
    judge_verdicts rows where answer_relevance_score or context_relevance_score
    is below the caller-supplied score_below. See module docstring -- these
    rows carry no classification, only matched_score_filter."""
    conditions = [
        "j.status = 'complete'",
        "(j.answer_relevance_score < %s OR j.context_relevance_score < %s)",
        "j.timestamp_utc >= NOW() - (%s * INTERVAL '1 minute')",
    ]
    params: list[Any] = [score_below, score_below, time_window_minutes]
    if endpoint is not None:
        conditions.append("r.endpoint = %s")
        params.append(endpoint)

    rows = await dao.fetch_all(
        f"""
        SELECT j.app_trace_id, j.status, r.endpoint, r.ticker, j.timestamp_utc,
               j.answer_relevance_score, j.context_relevance_score
        FROM judge_verdicts j
        LEFT JOIN rag_events r ON r.app_trace_id = j.app_trace_id
        WHERE {" AND ".join(conditions)}
        ORDER BY j.timestamp_utc DESC
        LIMIT {int(limit)}
        """,
        tuple(params),
    )
    traces = []
    for r in rows:
        matches = []
        ar = r["answer_relevance_score"]
        cr = r["context_relevance_score"]
        if ar is not None and ar < score_below:
            matches.append(
                ScoreFilterMatch(dimension="answer_relevance", score=ar, threshold=score_below)
            )
        if cr is not None and cr < score_below:
            matches.append(
                ScoreFilterMatch(dimension="context_relevance", score=cr, threshold=score_below)
            )
        traces.append(
            FailingTrace(
                app_trace_id=r["app_trace_id"],
                source="judge_verdict",
                status=r["status"],
                endpoint=r["endpoint"],
                ticker=r["ticker"],
                timestamp_utc=iso(r["timestamp_utc"]),
                matched_score_filter=matches,
            )
        )
    return traces


async def get_failing_traces(
    time_window_minutes: int = 60,
    endpoint: str | None = None,
    failure_type: FailureType = "any",
    limit: int = 50,
    score_below: float | None = None,
) -> GetFailingTracesResult:
    """Return traces where a guardrail blocked or errored the request, the
    judge pipeline failed to score it, or (if score_below is set) a complete
    judge verdict scored below an operator-chosen value on answer_relevance
    or context_relevance, over a time window.

    The incident entry point: "what's failing right now." Source: rag_events
    (status IN ('blocked','error')) and judge_verdicts (status IN
    ('partial','failed'), joined to rag_events for endpoint/ticker context).
    failure_type selects which source(s) to query; "any" queries both and
    merges by timestamp, each side independently bounded by limit. Every
    returned trace carries a `classification` derived from real persisted
    fields only (see module docstring): guardrail_blocked, rag_system_error,
    judge_skipped (nothing to evaluate -- total_gemini_calls=0), or
    judge_pipeline_failure (the judge ran and failed -- total_gemini_calls>0).

    classification_counts is a per-classification breakdown (only keys that
    are actually present), not a single collapsed "failure" scalar -- there
    is no uncontested line between "a failure" and "not a failure" across
    these four states (judge_skipped in particular is a consequence of an
    upstream block/error, not an independent failure, and must never be
    added into the same bucket as guardrail_blocked/rag_system_error/
    judge_pipeline_failure). Read the breakdown, not a sum of it.

    score_below (default None, unset -> no change in behavior) is NOT part of
    this failure taxonomy -- it is an operator-supplied investigation filter
    with no default threshold, because no calibrated platform threshold
    exists for answer_relevance or context_relevance. When set, it
    additionally returns status="complete" judge_verdicts rows scoring below
    that value, each carrying matched_score_filter (dimension + actual score)
    instead of a classification -- a filter match is explicitly not a
    failure verdict and is never counted in classification_counts.
    Faithfulness is excluded (see module docstring).
    """
    validate_limit(limit)
    traces: list[FailingTrace] = []

    if failure_type in ("blocked", "error", "any"):
        statuses = _RAG_EVENT_STATUSES[failure_type]
        traces.extend(
            await _fetch_rag_event_failures(time_window_minutes, endpoint, statuses, limit)
        )

    if failure_type in ("judge_failed", "any"):
        traces.extend(await _fetch_judge_failures(time_window_minutes, endpoint, limit))

    if score_below is not None:
        traces.extend(
            await _fetch_score_filtered_rows(time_window_minutes, endpoint, score_below, limit)
        )

    traces.sort(key=lambda t: t.timestamp_utc or "", reverse=True)
    traces = traces[:limit]

    classification_counts: dict[str, int] = {}
    for t in traces:
        if t.classification is not None:
            classification_counts[t.classification] = (
                classification_counts.get(t.classification, 0) + 1
            )
    score_filter_match_count = sum(1 for t in traces if t.matched_score_filter)
    unique_trace_count = len({t.app_trace_id for t in traces})

    return GetFailingTracesResult(
        traces=traces,
        classification_counts=classification_counts,
        score_filter_match_count=score_filter_match_count,
        unique_trace_count=unique_trace_count,
        risingwave_connected=dao.connected,
    )


@dataclass
class GuardrailDecisionSnapshot:
    app_trace_id: str
    found: bool
    status: str | None = None
    endpoint: str | None = None
    timestamp_utc: str | None = None
    input_rail_status: str | None = None
    block_reason: str | None = None
    block_rail: str | None = None
    output_rail_trace_snapshot: dict[str, Any] = field(default_factory=dict)
    risingwave_connected: bool = False
    note: str = ""


async def explain_guardrail_decision(app_trace_id: str) -> GuardrailDecisionSnapshot:
    """Return the persisted rail-decision snapshot for one request.

    This is the snapshot RagResponseEvent recorded at serving time --
    input_rail_status, block_reason, block_rail, and
    output_rail_trace_snapshot (a dict keyed by output rail name, e.g.
    output_trace["faithfulness"] = <that rail's RailDecision.details>).

    This is NOT a NeMo Colang/ExplainInfo execution trace. ExplainInfo
    exists only transiently in the gateway process for the single most
    recent check_async call on a shared LLMRails instance -- it is never
    persisted and is not indexed by app_trace_id, so it cannot be
    reconstructed for a past request from a separate process.
    """
    row = await dao.fetch_one(
        """
        SELECT app_trace_id, status, endpoint, timestamp_utc, input_rail_status,
               block_reason, block_rail, output_rail_trace_snapshot
        FROM rag_events
        WHERE app_trace_id = %s
        ORDER BY timestamp_utc DESC
        LIMIT 1
        """,
        (app_trace_id,),
    )
    if row is None:
        return GuardrailDecisionSnapshot(
            app_trace_id=app_trace_id,
            found=False,
            risingwave_connected=dao.connected,
            note=(
                "no matching rag_events row"
                if dao.connected
                else "RisingWave offline -- cannot look up this trace"
            ),
        )
    return GuardrailDecisionSnapshot(
        app_trace_id=app_trace_id,
        found=True,
        status=row["status"],
        endpoint=row["endpoint"],
        timestamp_utc=iso(row["timestamp_utc"]),
        input_rail_status=row["input_rail_status"],
        block_reason=row["block_reason"],
        block_rail=row["block_rail"],
        output_rail_trace_snapshot=row["output_rail_trace_snapshot"] or {},
        risingwave_connected=True,
        note="persisted rail-decision snapshot, not a NeMo ExplainInfo trace",
    )
