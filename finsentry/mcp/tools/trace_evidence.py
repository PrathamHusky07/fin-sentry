"""
search_traces and get_trace_detail: the Investigations list and the trace drill-down,
for an investigator that reasons over persisted traces.

Both reuse the dashboard's own trace queries and response models, so an agent sees the
same rows, judge states and frontier evidence as the Investigations page. Nothing is
re-derived here. The dashboard module takes its pool from finsentry/mcp/state.py, so
these functions run on the MCP server's RisingWave pool.

get_trace_detail withholds the fields whose redaction the producer does not guarantee.
Its docstring states the decision for each field and why.

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
# The query contract: keep the first MAX_QUERY_CHARS source characters and append "..." only
# when something was cut. A capped query is therefore at most MAX_QUERY_CHARS + 3 characters.
MAX_QUERY_CHARS = 500
_WITHHELD_NOTE = (
    "answer, error_detail, citation quotes and the frontier judge's rubric_reasoning "
    "are withheld by this tool. A stored query longer than "
    f"{MAX_QUERY_CHARS} characters keeps its first {MAX_QUERY_CHARS} characters, then '...'."
)


def _cap_query(query: str) -> str:
    """The first MAX_QUERY_CHARS characters plus "..." when the query was longer, else it
    unchanged. Output length is at most MAX_QUERY_CHARS + 3."""
    return query[:MAX_QUERY_CHARS] + "..." if len(query) > MAX_QUERY_CHARS else query


def _cap_list_query(item: TraceListItem) -> TraceListItem:
    return item.model_copy(update={"query": _cap_query(item.query)})


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
    never_evaluated. disagreement=True keeps only traces where the flash judge and the
    real frontier judge differ by 0.5 or more on faithfulness. disagreement=False keeps
    every other trace. That set includes traces the two tiers never both scored (blocked,
    never evaluated, not frontier-sampled), so False does not mean the tiers agreed.
    Omit disagreement to apply no filter; frontier_sampled works the same way.
    query_contains matches the stored (already redacted) query or the trace id. A row's
    query longer than 500 characters keeps its first 500 characters and then "...", as in
    get_trace_detail. Results are capped at 100 per page. Use next_offset to continue. Each
    row's app_trace_id is the id to pass to get_trace_detail, explain_guardrail_decision or
    get_judge_scores.
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
        traces=[_cap_list_query(TraceListItem(**r)) for r in rows],
        next_offset=offset + limit if len(rows) == limit else None,
        risingwave_connected=dao.connected,
    )


async def get_trace_detail(app_trace_id: str) -> TraceDetailResponse:
    """Return what is persisted for one request, minus the fields whose redaction is not
    guaranteed: the request status, ticker, block or error cause, retrieved chunk ids, the
    flash judge's three scores each with its own status, and the frontier judge's scores,
    verdict and cited chunk ids when the trace was sampled. found is False when no
    rag_events row matches.

    Per field, and why:
    - query: kept. A query longer than 500 characters keeps its first 500 characters and
      then "...", so it is at most 503 characters. The gateway persists the query after Presidio
      redaction and withholds it when redaction cannot run (_redact_for_persistence).
    - answer: withheld (null). It is the model's reply as generated. No output rail
      redacts personal data, so nothing proves it is safe. A blocked answer is never
      persisted either way.
    - citations: reduced to chunk_id. The quote is model-written text with the same
      gap as the answer. A chunk id is a corpus identifier.
    - error_detail: withheld (null). The gateway stores str(exception)[:500] for any
      unhandled error, which can hold connection strings or other secrets. error_kind,
      the exception class name, is kept.
    - rubric_reasoning (frontier): withheld (null). It is Gemini free text written
      about the answer and is not redacted.
    The note field says which fields this tool withheld. The dashboard route is unchanged.
    """
    detail = await _fetch_trace_detail(app_trace_id)
    if not detail.found:
        return detail
    query = _cap_query(detail.query) if detail.query is not None else None
    evidence = detail.frontier.evidence
    frontier = detail.frontier.model_copy(
        update={
            "evidence": evidence.model_copy(update={"rubric_reasoning": None})
            if evidence is not None
            else None
        }
    )
    return detail.model_copy(
        update={
            "query": query,
            "answer": None,
            "error_detail": None,
            "citations": [{"chunk_id": c["chunk_id"]} for c in detail.citations if "chunk_id" in c],
            "frontier": frontier,
            "note": f"{detail.note}. {_WITHHELD_NOTE}",
        }
    )
