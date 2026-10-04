"""
get_failing_traces and explain_guardrail_decision: both read individual rows
from the rag_events RisingWave source (not an aggregate materialized view --
these tools need per-trace detail, not window summaries). get_failing_traces
also reads judge_verdicts for judge-pipeline failures, joined back to
rag_events for endpoint/ticker context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from finsentry.mcp._util import iso
from finsentry.mcp.state import dao

FailureType = Literal["blocked", "error", "judge_failed", "any"]

_RAG_EVENT_STATUSES: dict[str, list[str]] = {
    "blocked": ["blocked"],
    "error": ["error"],
    "any": ["blocked", "error"],
}
_JUDGE_FAILURE_STATUSES = ["partial", "failed"]


@dataclass
class FailingTrace:
    app_trace_id: str
    source: Literal["rag_event", "judge_verdict"]
    status: str
    endpoint: str | None
    ticker: str | None
    timestamp_utc: str | None
    block_reason: str | None = None
    block_rail: str | None = None
    error_kind: str | None = None
    error_detail: str | None = None


@dataclass
class GetFailingTracesResult:
    traces: list[FailingTrace]
    count: int
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
        SELECT j.app_trace_id, j.status, r.endpoint, r.ticker, j.timestamp_utc
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
        )
        for r in rows
    ]


async def get_failing_traces(
    time_window_minutes: int = 60,
    endpoint: str | None = None,
    failure_type: FailureType = "any",
    limit: int = 50,
) -> GetFailingTracesResult:
    """Return traces where a guardrail blocked or errored the request, or
    the judge pipeline failed to score it, over a time window.

    The incident entry point: "what's failing right now." Source: rag_events
    (status IN ('blocked','error')) and judge_verdicts (status IN
    ('partial','failed'), joined to rag_events for endpoint/ticker context).
    failure_type selects which source(s) to query; "any" queries both and
    merges by timestamp, each side independently bounded by limit.
    """
    traces: list[FailingTrace] = []

    if failure_type in ("blocked", "error", "any"):
        statuses = _RAG_EVENT_STATUSES[failure_type]
        traces.extend(
            await _fetch_rag_event_failures(time_window_minutes, endpoint, statuses, limit)
        )

    if failure_type in ("judge_failed", "any"):
        traces.extend(await _fetch_judge_failures(time_window_minutes, endpoint, limit))

    traces.sort(key=lambda t: t.timestamp_utc or "", reverse=True)
    traces = traces[:limit]

    return GetFailingTracesResult(
        traces=traces,
        count=len(traces),
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
