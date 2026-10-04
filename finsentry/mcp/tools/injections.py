"""
search_prompt_injections: direct (input-rail-blocked) injection history over
a time window.

block_rail on rag_events is NOT the Python Rail.name -- it is the NeMo
Colang flow name the gateway passes through (finsentry/gateway/main.py:
block_rail=rail_name, from InputRailsAdapter.run()'s NeMo result.rail).
Confirmed empirically against a real blocked request during the Day 7 demo:
the persisted value was "check prompt injection" (finsentry/gateway/colang/
config.co), not "prompt-guard-2". "check hazard taxonomy" (Llama Guard 3) is
a different concern -- Meta's hazard/content-policy taxonomy, not prompt
injection -- so it is deliberately excluded here, not merged in.

Indirect/retrieval-rail injection detection runs today (RetrievalRail drops
a chunk when Prompt Guard 2 scores it above the 0.3 retrieval threshold --
see finsentry/rails/retrieval/rail.py) but the drop is only `log.warning`'d,
never written to a Kafka event or a RisingWave-queryable column. There is
nothing to query, so indirect clustering is not built here -- `indirect` is
always None with a reason, not a fabricated cluster.
"""
from __future__ import annotations

from dataclasses import dataclass

from finsentry.mcp._util import iso
from finsentry.mcp.state import dao

_DIRECT_INJECTION_RAILS = ["check prompt injection"]

_INDIRECT_DEFERRED_REASON = (
    "RetrievalRail drops a chunk when Prompt Guard 2 scores it above the "
    "retrieval threshold, but only logs the drop -- no Kafka event or "
    "RisingWave column persists it today. Indirect injection clustering is "
    "deferred until the event contract captures this signal."
)


@dataclass
class DirectInjectionEvent:
    app_trace_id: str
    endpoint: str | None
    block_rail: str | None
    block_reason: str | None
    timestamp_utc: str | None


@dataclass
class SearchPromptInjectionsResult:
    time_window_minutes: int
    direct: list[DirectInjectionEvent]
    direct_count_by_rail: dict[str, int]
    indirect: None
    indirect_deferred_reason: str
    risingwave_connected: bool


async def search_prompt_injections(
    time_window_minutes: int = 60, limit: int = 50
) -> SearchPromptInjectionsResult:
    """Direct (input-rail-blocked) injection attempts over a time window,
    counted by which rail blocked them. Source: rag_events where
    input_rail_status='blocked' and block_rail is the "check prompt
    injection" Colang flow. indirect is always None here -- see module
    docstring."""
    # LIMIT must be a const expression in RisingWave's streaming query
    # planner -- see finsentry/mcp/tools/traces.py for the same fix.
    rows = await dao.fetch_all(
        f"""
        SELECT app_trace_id, endpoint, block_rail, block_reason, timestamp_utc
        FROM rag_events
        WHERE input_rail_status = 'blocked'
          AND block_rail = ANY(%s)
          AND timestamp_utc >= NOW() - (%s * INTERVAL '1 minute')
        ORDER BY timestamp_utc DESC
        LIMIT {int(limit)}
        """,
        (_DIRECT_INJECTION_RAILS, time_window_minutes),
    )
    direct = [
        DirectInjectionEvent(
            app_trace_id=r["app_trace_id"],
            endpoint=r["endpoint"],
            block_rail=r["block_rail"],
            block_reason=r["block_reason"],
            timestamp_utc=iso(r["timestamp_utc"]),
        )
        for r in rows
    ]

    counts: dict[str, int] = {}
    for event in direct:
        if event.block_rail:
            counts[event.block_rail] = counts.get(event.block_rail, 0) + 1

    return SearchPromptInjectionsResult(
        time_window_minutes=time_window_minutes,
        direct=direct,
        direct_count_by_rail=counts,
        indirect=None,
        indirect_deferred_reason=_INDIRECT_DEFERRED_REASON,
        risingwave_connected=dao.connected,
    )
