"""
Minimal evaluation dashboard.

FastAPI app on port 8081. Queries the eight RisingWave materialized views
and renders a single-page HTML report. Designed for the interview demo:
it shows current-window quality metrics without requiring a frontend build.

Day 8: also serves /metrics/snapshot, the typed MetricsSnapshot contract the
gateway's SSE poller consumes (finsentry/events/metrics_snapshot.py) -- this
process keeps sole ownership of RisingWavePool; the gateway never imports it.

Routes:
    GET /                  -> HTML dashboard (latest window snapshot + backlog)
    GET /metrics           -> JSON payload (same data, machine-readable)
    GET /metrics/frontier  -> JSON frontier-tier verdict/disagreement counts (last 15m)
    GET /metrics/snapshot  -> typed MetricsSnapshot (internal contract for the gateway)
    GET /health            -> {"status": "ok"}
    GET /backlog           -> JSON consumer lag report

Environment variables:
    RISINGWAVE_HOST   (default: localhost)
    RISINGWAVE_PORT   (default: 4566)
    RISINGWAVE_USER   (default: root)
    RISINGWAVE_DB     (default: dev)
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from finsentry.consumer.lag_monitor import (
    ConsumerLagMonitor,
    ConsumerLagReport,
    lag_monitor_from_env,
)
from finsentry.events.metrics_snapshot import (
    FaithfulnessMetrics,
    FrontierMetrics,
    JudgeCostMetrics,
    MetricsSnapshot,
    RelevanceMetrics,
    ThroughputMetrics,
    TokenUsageMetrics,
    is_stale,
)
from finsentry.events.trace_api import (
    CalibrationHealthResponse,
    FlashJudgeView,
    FrontierEvidenceView,
    FrontierSectionView,
    JudgeState,
    TraceDetailResponse,
    TraceListItem,
    TraceListResponse,
)
from finsentry.mcp._util import validate_limit
from finsentry.mcp.tools.drift import get_drift_report
from finsentry.risingwave.dao import RisingWavePool

load_dotenv()

log = logging.getLogger(__name__)

_lag_monitor: ConsumerLagMonitor | None = None


def _to_jsonable(value: Any) -> Any:
    """Coerce RisingWave numeric types to JSON-serializable primitives.

    psycopg returns SQL NUMERIC/DECIMAL as Python Decimal, which stdlib
    json.dumps cannot encode. Recursively convert Decimal -> float across
    the nested metrics dict.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Database connection pool
# ---------------------------------------------------------------------------

_dao = RisingWavePool()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    global _lag_monitor
    await _dao.open()
    if _dao.connected:
        log.info("Dashboard connected to RisingWave")
    _lag_monitor = lag_monitor_from_env()
    yield
    await _dao.close()


app = FastAPI(title="FinSentry Evaluation Dashboard", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


async def _fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    return await _dao.fetch_one(sql, params)


async def _fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return await _dao.fetch_all(sql, params)


async def _fetch_metrics() -> dict[str, Any]:
    throughput = await _fetch_one(
        """
        SELECT total_requests, success_count, blocked_count, error_count,
               ROUND(avg_latency_ms::numeric, 1) AS avg_latency_ms,
               ROUND(p95_latency_ms::numeric, 1) AS p95_latency_ms,
               window_start, window_end
        FROM mv_request_throughput_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    faithfulness = await _fetch_one(
        """
        SELECT verdicts_count, ROUND(avg_faithfulness::numeric, 3) AS avg_faithfulness,
               complete_count, skipped_count, window_start, window_end
        FROM mv_faithfulness_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    relevance = await _fetch_one(
        """
        SELECT verdicts_count,
               ROUND(avg_answer_relevance::numeric, 3) AS avg_answer_relevance,
               ROUND(avg_context_relevance::numeric, 3) AS avg_context_relevance,
               window_start, window_end
        FROM mv_relevance_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    tokens = await _fetch_one(
        """
        SELECT input_tokens_total, output_tokens_total, thoughts_tokens_total,
               gemini_calls_total, cost_total_usd, window_start, window_end
        FROM mv_judge_usage_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    cost = await _fetch_one(
        """
        SELECT cost_total_usd, window_start, window_end
        FROM mv_judge_cost_1m
        ORDER BY window_end DESC
        LIMIT 1
        """
    )

    return {
        "throughput": throughput,
        "faithfulness": faithfulness,
        "relevance": relevance,
        "tokens": tokens,
        "cost": cost,
        "risingwave_connected": _dao.connected,
    }


_FRONTIER_WINDOW_MINUTES = 15


async def _fetch_frontier_metrics() -> dict[str, Any]:
    verdict_rows = await _fetch_all(
        f"""
        SELECT verdict, SUM(verdict_count) AS count
        FROM mv_frontier_verdict_rate_1m
        WHERE window_start >= NOW() - INTERVAL '{_FRONTIER_WINDOW_MINUTES} minutes'
        GROUP BY verdict
        """
    )
    disagreement_rows = await _fetch_all(
        f"""
        SELECT disagreement_classification, SUM(disagreement_count) AS count
        FROM mv_frontier_disagreement_1m
        WHERE window_start >= NOW() - INTERVAL '{_FRONTIER_WINDOW_MINUTES} minutes'
        GROUP BY disagreement_classification
        """
    )

    return {
        "window_minutes": _FRONTIER_WINDOW_MINUTES,
        "verdict_counts": {row["verdict"]: row["count"] for row in verdict_rows},
        "disagreement_counts": {
            row["disagreement_classification"]: row["count"] for row in disagreement_rows
        },
        "risingwave_connected": _dao.connected,
    }


async def _fetch_frontier_latest_window_end() -> datetime.datetime | None:
    """The one anchor timestamp mv_frontier_verdict_rate_1m's SUM-over-15-minutes
    query never needed before: without it, the frontier section of a
    MetricsSnapshot has no window_end to judge freshness against. Not a new
    metric -- the same lookback, one extra MAX() column."""
    row = await _fetch_one(
        f"""
        SELECT MAX(window_end) AS latest_window_end
        FROM mv_frontier_verdict_rate_1m
        WHERE window_start >= NOW() - INTERVAL '{_FRONTIER_WINDOW_MINUTES} minutes'
        """
    )
    return row["latest_window_end"] if row else None


def _throughput_section(
    raw: dict[str, Any] | None, now: datetime.datetime
) -> ThroughputMetrics | None:
    if raw is None:
        return None
    return ThroughputMetrics(
        total_requests=raw["total_requests"],
        success_count=raw["success_count"],
        blocked_count=raw["blocked_count"],
        error_count=raw["error_count"],
        avg_latency_ms=raw["avg_latency_ms"],
        p95_latency_ms=raw["p95_latency_ms"],
        window_start=raw["window_start"],
        window_end=raw["window_end"],
        stale=is_stale(raw["window_end"], now=now),
    )


def _faithfulness_section(
    raw: dict[str, Any] | None, now: datetime.datetime
) -> FaithfulnessMetrics | None:
    if raw is None:
        return None
    return FaithfulnessMetrics(
        verdicts_count=raw["verdicts_count"],
        avg_faithfulness=raw["avg_faithfulness"],
        complete_count=raw["complete_count"],
        skipped_count=raw["skipped_count"],
        window_start=raw["window_start"],
        window_end=raw["window_end"],
        stale=is_stale(raw["window_end"], now=now),
    )


def _relevance_section(
    raw: dict[str, Any] | None, now: datetime.datetime
) -> RelevanceMetrics | None:
    if raw is None:
        return None
    return RelevanceMetrics(
        verdicts_count=raw["verdicts_count"],
        avg_answer_relevance=raw["avg_answer_relevance"],
        avg_context_relevance=raw["avg_context_relevance"],
        window_start=raw["window_start"],
        window_end=raw["window_end"],
        stale=is_stale(raw["window_end"], now=now),
    )


def _tokens_section(raw: dict[str, Any] | None, now: datetime.datetime) -> TokenUsageMetrics | None:
    if raw is None:
        return None
    return TokenUsageMetrics(
        input_tokens_total=raw["input_tokens_total"],
        output_tokens_total=raw["output_tokens_total"],
        thoughts_tokens_total=raw["thoughts_tokens_total"],
        gemini_calls_total=raw["gemini_calls_total"],
        cost_total_usd=raw["cost_total_usd"],
        window_start=raw["window_start"],
        window_end=raw["window_end"],
        stale=is_stale(raw["window_end"], now=now),
    )


def _cost_section(raw: dict[str, Any] | None, now: datetime.datetime) -> JudgeCostMetrics | None:
    if raw is None:
        return None
    return JudgeCostMetrics(
        cost_total_usd=raw["cost_total_usd"],
        window_start=raw["window_start"],
        window_end=raw["window_end"],
        stale=is_stale(raw["window_end"], now=now),
    )


def _frontier_section(
    raw: dict[str, Any], latest_window_end: datetime.datetime | None, now: datetime.datetime
) -> FrontierMetrics:
    return FrontierMetrics(
        window_minutes=raw["window_minutes"],
        verdict_counts=raw["verdict_counts"],
        disagreement_counts=raw["disagreement_counts"],
        latest_window_end=latest_window_end,
        stale=is_stale(latest_window_end, now=now),
    )


async def _build_snapshot() -> MetricsSnapshot:
    now = datetime.datetime.now(datetime.UTC)
    metrics = await _fetch_metrics()
    frontier = await _fetch_frontier_metrics()
    frontier_latest_window_end = await _fetch_frontier_latest_window_end()

    return MetricsSnapshot(
        generated_at=now,
        risingwave_connected=metrics["risingwave_connected"],
        throughput=_throughput_section(metrics["throughput"], now),
        faithfulness=_faithfulness_section(metrics["faithfulness"], now),
        relevance=_relevance_section(metrics["relevance"], now),
        tokens=_tokens_section(metrics["tokens"], now),
        cost=_cost_section(metrics["cost"], now),
        frontier=_frontier_section(frontier, frontier_latest_window_end, now),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/backlog")
async def backlog() -> JSONResponse:
    if _lag_monitor is None:
        return JSONResponse({"error": "lag monitor not initialized"}, status_code=503)
    report = await _lag_monitor.fetch_lag()
    return JSONResponse(
        content={
            "group_id": report.group_id,
            "total_lag": report.total_lag,
            "ok": report.ok,
            "error": report.error,
            "partitions": [
                {
                    "topic": p.topic,
                    "partition": p.partition,
                    "end_offset": p.end_offset,
                    "committed_offset": p.committed_offset,
                    "lag": p.lag,
                }
                for p in report.partitions
            ],
        }
    )


@app.get("/metrics")
async def metrics() -> JSONResponse:
    data = await _fetch_metrics()
    return JSONResponse(content=_to_jsonable(data))


@app.get("/metrics/frontier")
async def frontier_metrics() -> JSONResponse:
    data = await _fetch_frontier_metrics()
    return JSONResponse(content=_to_jsonable(data))


@app.get("/metrics/snapshot", response_model=MetricsSnapshot)
async def metrics_snapshot() -> MetricsSnapshot:
    """Internal contract for the gateway's SSE poller (Option C) -- not a
    public-facing route. See finsentry/events/metrics_snapshot.py."""
    return await _build_snapshot()


# ---------------------------------------------------------------------------
# Trace investigation (Day 9): Judge Panel list, trace drill-down,
# calibration-health panel. Internal contracts for the gateway's httpx
# proxy routes (Option C) -- not public-facing routes. See
# finsentry/events/trace_api.py for the four-state judge model and the
# frontier stub-filtering rule these build.
# ---------------------------------------------------------------------------

_REAL_FRONTIER_JUDGE_ID: Literal["gemini-rubric"] = "gemini-rubric"


def _classify_judge_state(judge_status: str | None, rag_status: str) -> JudgeState:
    if judge_status is None:
        return "never_evaluated"
    if judge_status == "complete":
        return "evaluated"
    if judge_status == "partial":
        return "partially_evaluated"
    # judge_status == "failed" (or any other unrecognized status): a real
    # rag_status="success" row with no complete metric is a judge-pipeline
    # outage, not a guardrail block -- see finsentry/events/trace_api.py.
    if rag_status == "success":
        return "judge_failed"
    return "blocked_before_evaluation"


# Translates the public five-state judge_state filter back to the raw
# judge_verdicts.status / rag_events.status condition _classify_judge_state
# derives it from -- the dashboard never stores judge_state itself.
_JUDGE_STATE_TO_STATUS_SQL: dict[str, str] = {
    "never_evaluated": "j.status IS NULL",
    "evaluated": "j.status = 'complete'",
    "partially_evaluated": "j.status = 'partial'",
    "blocked_before_evaluation": "j.status = 'failed' AND r.status != 'success'",
    "judge_failed": "j.status = 'failed' AND r.status = 'success'",
}


async def _fetch_trace_list(
    limit: int,
    offset: int,
    ticker: str | None,
    rag_status: str | None,
    q: str | None = None,
    judge_state: str | None = None,
    frontier_sampled: bool | None = None,
    disagreement: bool | None = None,
) -> list[dict[str, Any]]:
    validate_limit(limit)
    conditions: list[str] = []
    params: list[Any] = []
    if ticker is not None:
        conditions.append("r.ticker = %s")
        params.append(ticker)
    if rag_status is not None:
        conditions.append("r.status = %s")
        params.append(rag_status)
    if q is not None:
        conditions.append("(r.query ILIKE %s OR r.app_trace_id ILIKE %s)")
        pattern = f"%{q}%"
        params.extend([pattern, pattern])
    if judge_state is not None:
        conditions.append(_JUDGE_STATE_TO_STATUS_SQL[judge_state])
    if frontier_sampled is not None:
        sampled_ids = list(await _fetch_frontier_sampled_ids())
        if frontier_sampled:
            conditions.append("r.app_trace_id = ANY(%s)")
            params.append(sampled_ids)
        else:
            conditions.append("NOT (r.app_trace_id = ANY(%s))")
            params.append(sampled_ids)
    if disagreement:
        conditions.append("r.app_trace_id = ANY(%s)")
        params.append(list(await _fetch_disagreement_trace_ids()))
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # LIMIT/OFFSET must be const expressions in RisingWave's streaming query
    # planner, not bound parameters -- both are already int-typed by this
    # function's own signature, so inlining is safe (same pattern as
    # finsentry/mcp/tools/traces.py).
    # Latest-verdict-per-trace, matching _fetch_trace_detail's
    # ORDER BY timestamp_utc DESC LIMIT 1 rule -- a plain LEFT JOIN fans out
    # one row per (trace, verdict) pair and silently disagrees with the
    # detail endpoint once a trace has more than one judge_verdicts row
    # (retried evaluation, a re-score). DISTINCT would hide the fan-out
    # without fixing which verdict wins; the window function picks the same
    # row the detail endpoint would show.
    rows = await _fetch_all(
        f"""
        SELECT r.app_trace_id, r.timestamp_utc, r.endpoint, r.ticker, r.query,
               r.status AS rag_status, r.block_reason, j.status AS judge_status
        FROM rag_events r
        LEFT JOIN (
            SELECT app_trace_id, status,
                   ROW_NUMBER() OVER (
                       PARTITION BY app_trace_id ORDER BY timestamp_utc DESC
                   ) AS rn
            FROM judge_verdicts
        ) j ON j.app_trace_id = r.app_trace_id AND j.rn = 1
        {where_clause}
        ORDER BY r.timestamp_utc DESC
        LIMIT {int(limit)} OFFSET {int(offset)}
        """,
        tuple(params),
    )

    trace_ids = [r["app_trace_id"] for r in rows]
    sampled_ids_for_page: set[str] = set()
    if trace_ids:
        sampled_rows = await _fetch_all(
            "SELECT DISTINCT app_trace_id FROM rag_frontier_verdicts WHERE app_trace_id = ANY(%s)",
            (trace_ids,),
        )
        sampled_ids_for_page = {r["app_trace_id"] for r in sampled_rows}

    return [
        {
            "app_trace_id": r["app_trace_id"],
            "timestamp_utc": r["timestamp_utc"],
            "endpoint": r["endpoint"],
            "ticker": r["ticker"],
            "query": r["query"],
            "rag_status": r["rag_status"],
            "block_reason": r["block_reason"],
            "judge_state": _classify_judge_state(r["judge_status"], r["rag_status"]),
            "frontier_sampled": r["app_trace_id"] in sampled_ids_for_page,
        }
        for r in rows
    ]


async def _fetch_frontier_sampled_ids() -> set[str]:
    rows = await _fetch_all("SELECT DISTINCT app_trace_id FROM rag_frontier_verdicts")
    return {r["app_trace_id"] for r in rows}


def _real_frontier_evidence(per_judge_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one real, non-stub, non-null-evidence gemini-rubric entry in a
    per_judge_results array, or None. Never picks a stub-a/stub-b/test-judge
    entry, and never picks an entry whose evidence is null -- both are
    confirmed to occur in real persisted rows (see docs/build-log.md)."""
    for j in per_judge_results:
        if j.get("judge_id") == _REAL_FRONTIER_JUDGE_ID and j.get("evidence") is not None:
            return j
    return None


# A flash score and a real frontier gemini-rubric score this far apart counts
# as a cross-tier disagreement worth surfacing. A UI display cutoff, not a
# swept classifier threshold -- see docs/internal/day9-frontend-data-contract.md.
_DISAGREEMENT_SCORE_DELTA = 0.5


async def _fetch_disagreement_trace_ids() -> set[str]:
    """Traces where the flash tier and the real frontier gemini-rubric
    judge substantially disagree on faithfulness -- never
    disagreement_classification, which classifies disagreement within the
    frontier ensemble's own judges, not between flash and frontier (see
    data contract). Picks the latest-by-evaluation_ts frontier row per
    trace, same rule as _fetch_frontier_section, and only ever a real
    non-stub gemini-rubric entry via _real_frontier_evidence."""
    rows = await _fetch_all(
        """
        SELECT r.app_trace_id, j.faithfulness_score AS flash_score,
               f.per_judge_results, f.evaluation_ts
        FROM rag_events r
        JOIN (
            SELECT app_trace_id, faithfulness_score, faithfulness_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY app_trace_id ORDER BY timestamp_utc DESC
                   ) AS rn
            FROM judge_verdicts
        ) j ON j.app_trace_id = r.app_trace_id AND j.rn = 1
        JOIN rag_frontier_verdicts f ON f.app_trace_id = r.app_trace_id
        WHERE j.faithfulness_status = 'complete'
        """
    )

    latest_by_trace: dict[str, dict[str, Any]] = {}
    for row in rows:
        existing = latest_by_trace.get(row["app_trace_id"])
        if existing is None or row["evaluation_ts"] > existing["evaluation_ts"]:
            latest_by_trace[row["app_trace_id"]] = row

    disagreement_ids: set[str] = set()
    for trace_id, row in latest_by_trace.items():
        real = _real_frontier_evidence(row["per_judge_results"] or [])
        if real is None:
            continue
        frontier_score = real.get("faithfulness_score")
        flash_score = row["flash_score"]
        if frontier_score is None or flash_score is None:
            continue
        if abs(flash_score - frontier_score) >= _DISAGREEMENT_SCORE_DELTA:
            disagreement_ids.add(trace_id)
    return disagreement_ids


async def _fetch_frontier_section(app_trace_id: str) -> FrontierSectionView:
    # Most recent row by evaluation_ts: confirmed against every real
    # duplicate-trace case today that this is the real gemini-rubric row,
    # never the earlier stub placeholder (see docs/build-log.md).
    row = await _fetch_one(
        """
        SELECT verdict, per_judge_results, evaluation_ts
        FROM rag_frontier_verdicts
        WHERE app_trace_id = %s
        ORDER BY evaluation_ts DESC
        LIMIT 1
        """,
        (app_trace_id,),
    )
    if row is None:
        return FrontierSectionView(
            sampled=False, evidence=None, note="frontier not sampled for this trace"
        )

    real = _real_frontier_evidence(row["per_judge_results"] or [])
    if real is None:
        return FrontierSectionView(
            sampled=True,
            evidence=None,
            note="frontier evaluated with no real judge recorded",
        )

    evidence = real["evidence"] or {}
    return FrontierSectionView(
        sampled=True,
        evidence=FrontierEvidenceView(
            judge_id=_REAL_FRONTIER_JUDGE_ID,
            faithfulness_score=real.get("faithfulness_score"),
            rubric_reasoning=evidence.get("rubric_reasoning"),
            cited_chunks_supporting=evidence.get("cited_chunks_supporting") or [],
            cited_chunks_contradicting=evidence.get("cited_chunks_contradicting") or [],
            verdict=row["verdict"],
            evaluation_ts=row["evaluation_ts"],
        ),
        note="real gemini-rubric evidence for this trace",
    )


async def _fetch_trace_detail(app_trace_id: str) -> TraceDetailResponse:
    rag_row = await _fetch_one(
        """
        SELECT app_trace_id, status, endpoint, ticker, query, answer, confidence,
               model_used, citations, retrieved_chunk_ids, block_reason, block_rail,
               error_kind, error_detail, timestamp_utc
        FROM rag_events
        WHERE app_trace_id = %s
        ORDER BY timestamp_utc DESC
        LIMIT 1
        """,
        (app_trace_id,),
    )
    if rag_row is None:
        return TraceDetailResponse(
            app_trace_id=app_trace_id,
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
            frontier=FrontierSectionView(
                sampled=False, evidence=None, note="frontier not sampled for this trace"
            ),
            risingwave_connected=_dao.connected,
            note="no matching rag_events row" if _dao.connected else "RisingWave offline",
        )

    judge_row = await _fetch_one(
        """
        SELECT status, timestamp_utc, faithfulness_score, faithfulness_status,
               answer_relevance_score, answer_relevance_status,
               context_relevance_score, context_relevance_status
        FROM judge_verdicts
        WHERE app_trace_id = %s
        ORDER BY timestamp_utc DESC
        LIMIT 1
        """,
        (app_trace_id,),
    )
    flash = (
        FlashJudgeView(
            status=judge_row["status"],
            timestamp_utc=judge_row["timestamp_utc"],
            faithfulness_score=judge_row["faithfulness_score"],
            faithfulness_status=judge_row["faithfulness_status"],
            answer_relevance_score=judge_row["answer_relevance_score"],
            answer_relevance_status=judge_row["answer_relevance_status"],
            context_relevance_score=judge_row["context_relevance_score"],
            context_relevance_status=judge_row["context_relevance_status"],
        )
        if judge_row is not None
        else None
    )

    frontier = await _fetch_frontier_section(app_trace_id)

    return TraceDetailResponse(
        app_trace_id=app_trace_id,
        found=True,
        rag_status=rag_row["status"],
        endpoint=rag_row["endpoint"],
        ticker=rag_row["ticker"],
        query=rag_row["query"],
        answer=rag_row["answer"],
        confidence=rag_row["confidence"],
        model_used=rag_row["model_used"],
        citations=rag_row["citations"] or [],
        retrieved_chunk_ids=rag_row["retrieved_chunk_ids"] or [],
        block_reason=rag_row["block_reason"],
        block_rail=rag_row["block_rail"],
        error_kind=rag_row["error_kind"],
        error_detail=rag_row["error_detail"],
        timestamp_utc=rag_row["timestamp_utc"],
        judge_state=_classify_judge_state(
            judge_row["status"] if judge_row else None, rag_row["status"]
        ),
        flash=flash,
        frontier=frontier,
        risingwave_connected=_dao.connected,
        note="persisted trace snapshot",
    )


def _calibration_position(
    kappa: float | None, entry_threshold: float, recovery_threshold: float
) -> Literal[
    "at_or_above_recovery", "between_thresholds", "at_or_below_entry", "insufficient_data"
]:
    if kappa is None:
        return "insufficient_data"
    if kappa >= recovery_threshold:
        return "at_or_above_recovery"
    if kappa <= entry_threshold:
        return "at_or_below_entry"
    return "between_thresholds"


async def _fetch_calibration_health() -> CalibrationHealthResponse:
    """Current position vs. the Day 6 DriftConfig thresholds, reusing
    get_drift_report (finsentry/mcp/tools/drift.py) as the query source of
    truth -- it reads the real canary artifact and the live DriftConfig
    policy, no RisingWave access. One point-in-time panel, never a trend
    chart: only one real historical kappa observation exists on disk."""
    report = await get_drift_report()
    reading = report.last_health_reading
    kappa = reading.kappa if reading is not None else None
    return CalibrationHealthResponse(
        judge_id=report.judge_id,
        kappa=kappa,
        state=reading.state if reading is not None else None,
        window_n=reading.window_n if reading is not None else None,
        min_n=report.policy.min_n,
        healthy_baseline_kappa=report.policy.healthy_baseline_kappa,
        drift_entry_threshold=report.policy.drift_entry_threshold,
        recovery_threshold=report.policy.recovery_threshold,
        position=_calibration_position(
            kappa, report.policy.drift_entry_threshold, report.policy.recovery_threshold
        ),
        state_as_of=reading.state_as_of if reading is not None else None,
        note=report.note,
    )


@app.get("/traces", response_model=TraceListResponse)
async def traces(
    limit: int = 50,
    offset: int = 0,
    ticker: str | None = None,
    status: str | None = None,
    q: str | None = None,
    judge_state: str | None = None,
    frontier_sampled: bool | None = None,
    disagreement: bool | None = None,
) -> TraceListResponse:
    """Internal contract for the gateway's /ops/traces proxy (Investigations
    table) -- not a public-facing route."""
    rows = await _fetch_trace_list(
        limit, offset, ticker, status, q, judge_state, frontier_sampled, disagreement
    )
    return TraceListResponse(
        traces=[TraceListItem(**r) for r in rows],
        next_offset=offset + limit if len(rows) == limit else None,
        risingwave_connected=_dao.connected,
    )


@app.get("/traces/{app_trace_id}", response_model=TraceDetailResponse)
async def trace_detail(app_trace_id: str) -> TraceDetailResponse:
    """Internal contract for the gateway's /ops/traces/{id} proxy (trace
    drill-down) -- not a public-facing route."""
    return await _fetch_trace_detail(app_trace_id)


@app.get("/calibration/health", response_model=CalibrationHealthResponse)
async def calibration_health() -> CalibrationHealthResponse:
    """Internal contract for the gateway's /ops/calibration/health proxy
    (calibration-health panel) -- not a public-facing route."""
    return await _fetch_calibration_health()


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    data = await _fetch_metrics()
    lag_report: ConsumerLagReport | None = None
    if _lag_monitor is not None:
        lag_report = await _lag_monitor.fetch_lag()
    return HTMLResponse(content=_render_html(data, lag_report))


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------


def _fmt(value: Any, suffix: str = "", na: str = "—") -> str:
    if value is None:
        return na
    return f"{value}{suffix}"


def _fmt_cost(value: Any, na: str = "—") -> str:
    if value is None:
        return na
    return f"${float(value):.6f}"


def _render_html(data: dict[str, Any], lag_report: ConsumerLagReport | None = None) -> str:
    tp = data.get("throughput") or {}
    fa = data.get("faithfulness") or {}
    re = data.get("relevance") or {}
    tok = data.get("tokens") or {}
    cost = data.get("cost") or {}
    connected = data.get("risingwave_connected", False)

    if lag_report is not None and lag_report.ok:
        lag_str = str(lag_report.total_lag)
        lag = lag_report.total_lag
        if lag < 100:
            lag_color = "#22c55e"
        elif lag < 1000:
            lag_color = "#f59e0b"
        else:
            lag_color = "#ef4444"
        backlog_html = f"""
  <p class="section-title">Consumer Backlog</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Total Lag</div>
      <div class="card-value" style="color:{lag_color}">{lag_str}</div>
      <div class="card-sub">messages behind for group {lag_report.group_id}</div>
    </div>
  </div>"""
    elif lag_report is not None:
        backlog_html = f"""
  <p class="section-title">Consumer Backlog</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Total Lag</div>
      <div class="card-value">—</div>
      <div class="card-sub" style="color:#ef4444">Admin API error: {lag_report.error}</div>
    </div>
  </div>"""
    else:
        backlog_html = ""

    connection_badge = (
        '<span style="color:#22c55e">&#9679; RisingWave connected</span>'
        if connected
        else '<span style="color:#ef4444">&#9679; RisingWave offline (static demo)</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>FinSentry Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
            padding: 2rem; max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #94a3b8; font-size: 0.875rem; margin-bottom: 2rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
             gap: 1rem; margin-bottom: 2rem; }}
    .card {{ background: #1e293b; border-radius: 0.75rem; padding: 1.25rem;
             border: 1px solid #334155; }}
    .card-label {{ color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
                   letter-spacing: 0.05em; margin-bottom: 0.5rem; }}
    .card-value {{ font-size: 1.75rem; font-weight: 700; color: #f1f5f9; }}
    .card-sub {{ color: #64748b; font-size: 0.75rem; margin-top: 0.25rem; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b;
             border-radius: 0.75rem; overflow: hidden; border: 1px solid #334155; }}
    th {{ text-align: left; padding: 0.75rem 1rem; color: #94a3b8;
          font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
          border-bottom: 1px solid #334155; }}
    td {{ padding: 0.75rem 1rem; font-size: 0.875rem; border-bottom: 1px solid #1e293b; }}
    tr:last-child td {{ border-bottom: none; }}
    .section-title {{ font-size: 1rem; font-weight: 600; margin: 1.5rem 0 0.75rem; }}
  </style>
</head>
<body>
  <h1>FinSentry Evaluation Dashboard</h1>
  <p class="subtitle">{connection_badge} &nbsp;&bull;&nbsp; Real-time quality metrics</p>

  <p class="section-title">Request Throughput (last 1-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Total Requests</div>
      <div class="card-value">{_fmt(tp.get("total_requests"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Success Rate</div>
      <div class="card-value">{_success_rate(tp)}</div>
    </div>
    <div class="card">
      <div class="card-label">Avg Latency</div>
      <div class="card-value">{_fmt(tp.get("avg_latency_ms"), " ms")}</div>
    </div>
    <div class="card">
      <div class="card-label">p95 Latency</div>
      <div class="card-value">{_fmt(tp.get("p95_latency_ms"), " ms")}</div>
    </div>
  </div>

  <p class="section-title">Quality Scores (last 1-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Faithfulness</div>
      <div class="card-value">{_fmt(fa.get("avg_faithfulness"))}</div>
      <div class="card-sub">{_fmt(fa.get("verdicts_count"))} verdicts</div>
    </div>
    <div class="card">
      <div class="card-label">Answer Relevance</div>
      <div class="card-value">{_fmt(re.get("avg_answer_relevance"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Context Relevance</div>
      <div class="card-value">{_fmt(re.get("avg_context_relevance"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Faithfulness Skip Rate</div>
      <div class="card-value">{_skip_rate(fa)}</div>
      <div class="card-sub">of {_fmt(fa.get("verdicts_count"))} verdicts</div>
    </div>
  </div>

  <p class="section-title">Gemini Token Usage (last 1-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Input Tokens</div>
      <div class="card-value">{_fmt(tok.get("input_tokens_total"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Output Tokens</div>
      <div class="card-value">{_fmt(tok.get("output_tokens_total"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Thoughts Tokens</div>
      <div class="card-value">{_fmt(tok.get("thoughts_tokens_total"))}</div>
    </div>
    <div class="card">
      <div class="card-label">Gemini Calls</div>
      <div class="card-value">{_fmt(tok.get("gemini_calls_total"))}</div>
    </div>
  </div>

  <p class="section-title">Judge Cost (last 1-minute window)</p>
  <div class="grid">
    <div class="card">
      <div class="card-label">Total Cost (USD)</div>
      <div class="card-value">{_fmt_cost(cost.get("cost_total_usd"))}</div>
      <div class="card-sub">Vertex AI Standard tier pricing</div>
    </div>
    <div class="card">
      <div class="card-label">Cost (from usage view)</div>
      <div class="card-value">{_fmt_cost(tok.get("cost_total_usd"))}</div>
      <div class="card-sub">Cross-check via mv_judge_usage_1m</div>
    </div>
  </div>
  {backlog_html}
</body>
</html>"""


def _success_rate(tp: dict[str, Any]) -> str:
    total = tp.get("total_requests")
    success = tp.get("success_count")
    if total is None or success is None or total == 0:
        return "—"
    return f"{100 * success / total:.1f}%"


def _skip_rate(fa: dict[str, Any]) -> str:
    skipped = fa.get("skipped_count")
    total = fa.get("verdicts_count")
    if skipped is None or total is None or total == 0:
        return "—"
    return f"{100 * skipped / total:.1f}%"
