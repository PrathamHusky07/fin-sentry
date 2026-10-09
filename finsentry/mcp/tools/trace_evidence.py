"""
search_traces and get_trace_detail: the Investigations list and the trace drill-down,
for an investigator that reasons over persisted traces.

Both reuse the dashboard's own trace queries and response models, so an agent sees the
same rows, judge states and frontier evidence as the Investigations page. Nothing is
re-derived here. The dashboard module takes its pool from finsentry/mcp/state.py, so
these functions run on the MCP server's RisingWave pool.

A failed or unavailable RisingWave raises instead of returning an empty result, because
an empty list would read as "nothing happened". The MCP SDK surfaces the raise as an
error result with the fixed message from the DAO, never a stack trace.
"""

from __future__ import annotations

from finsentry.dashboard.app import _fetch_trace_detail, _fetch_trace_list
from finsentry.events.trace_api import (
    JudgeState,
    TraceDetailResponse,
    TraceListItem,
    TraceListResponse,
)
from finsentry.mcp._util import validate_limit
from finsentry.mcp.state import dao

MAX_TRACE_PAGE = 100


async def search_traces(
    limit: int = 20,
    offset: int = 0,
    ticker: str | None = None,
    rag_status: str | None = None,
    query_contains: str | None = None,
    judge_state: JudgeState | None = None,
    frontier_sampled: bool | None = None,
    disagreement: bool | None = None,
) -> TraceListResponse:
    """List persisted traces, newest first, with the Investigations filters.

    rag_status is the request status (success, blocked or error). judge_state is one of
    evaluated, partially_evaluated, blocked_before_evaluation, judge_failed or
    never_evaluated. disagreement=True keeps traces where the flash judge and the real
    frontier judge differ by 0.5 or more on faithfulness. query_contains matches the
    stored (already redacted) query or the trace id. Results are capped at 100 per
    page. Use next_offset to continue. Each row's app_trace_id is the id to pass to
    get_trace_detail, explain_guardrail_decision or get_judge_scores.
    """
    validate_limit(limit, MAX_TRACE_PAGE)
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    rows = await _fetch_trace_list(
        limit,
        offset,
        ticker,
        rag_status,
        query_contains,
        judge_state,
        frontier_sampled,
        disagreement,
    )
    return TraceListResponse(
        traces=[TraceListItem(**r) for r in rows],
        next_offset=offset + limit if len(rows) == limit else None,
        risingwave_connected=dao.connected,
    )


async def get_trace_detail(app_trace_id: str) -> TraceDetailResponse:
    """Return everything persisted for one request: the stored query and answer, the
    citations and retrieved chunk ids, the block or error cause, the flash judge's three
    scores each with its own status, and the frontier judge's evidence when the trace was
    sampled. found is False when no rag_events row matches. A blocked answer is never
    persisted, so answer is empty for a blocked trace."""
    return await _fetch_trace_detail(app_trace_id)
