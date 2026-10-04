"""
MetricsSnapshot: the typed contract for the Day 8 Live Operations SSE feed.

Formalizes the shape finsentry/dashboard/app.py's _fetch_metrics() and
_fetch_frontier_metrics() already return as an untyped dict, so the gateway
(which must never import RisingWave -- Option C) and the dashboard (which
owns RisingWavePool) can share one typed contract instead of each inventing
its own parsing of the other's JSON.

Freshness is per-section, not a single global flag. The sections are built
from materialized views with genuinely different bucket/window semantics
(infra/risingwave/init.sql):
  - throughput/faithfulness/relevance/tokens/cost all come from 1-minute
    date_trunc('minute', ...) buckets, each queried as "latest single
    bucket" (ORDER BY window_end DESC LIMIT 1). A single bucket's own
    window_end is a real anchor to compare against now.
  - frontier (verdict/disagreement counts) sums many 1-minute buckets over
    a 15-minute lookback (WHERE window_start >= NOW() - INTERVAL '15
    minutes'), which has no single natural window_end -- the dashboard's
    existing query never selected one. There is no way to derive a
    freshness verdict for this section without an anchor timestamp, so its
    query gains one extra scalar (MAX(window_end) over the same lookback)
    -- not a new metric or aggregation dimension, just the timestamp this
    freshness rule requires.

The rule, applied uniformly once each section has its own anchor: stale if
now - window_end > 2 * that section's own bucket width (1 minute). A
missing anchor (no row at all, or zero frontier activity in the lookback)
is stale=True by construction -- the conservative default when the data
cannot distinguish "nothing happened" from "the pipeline is dead," not a
fabricated verdict either way.

There is deliberately no single top-level `stale` boolean: collapsing six
sections sourced from different Kafka topics into one flag would hide the
case where, say, rag_events is flowing but the judge consumer has died.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

_BUCKET_WIDTH_1M = timedelta(minutes=1)
_FRESHNESS_GRACE_MULTIPLIER = 2
_STALE_AFTER = _BUCKET_WIDTH_1M * _FRESHNESS_GRACE_MULTIPLIER


def is_stale(window_end: datetime | None, *, now: datetime) -> bool:
    """Shared freshness rule: stale if there is no anchor, or the anchor is
    older than 2x the 1-minute bucket width every section here is built
    from. See module docstring for why this isn't a single global flag."""
    if window_end is None:
        return True
    return (now - window_end) > _STALE_AFTER


class ThroughputMetrics(BaseModel):
    total_requests: int | None = None
    success_count: int | None = None
    blocked_count: int | None = None
    error_count: int | None = None
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    stale: bool


class FaithfulnessMetrics(BaseModel):
    verdicts_count: int | None = None
    avg_faithfulness: float | None = None
    complete_count: int | None = None
    skipped_count: int | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    stale: bool


class RelevanceMetrics(BaseModel):
    verdicts_count: int | None = None
    avg_answer_relevance: float | None = None
    avg_context_relevance: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    stale: bool


class TokenUsageMetrics(BaseModel):
    input_tokens_total: int | None = None
    output_tokens_total: int | None = None
    thoughts_tokens_total: int | None = None
    gemini_calls_total: int | None = None
    cost_total_usd: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    stale: bool


class JudgeCostMetrics(BaseModel):
    cost_total_usd: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    stale: bool


class FrontierMetrics(BaseModel):
    window_minutes: int
    verdict_counts: dict[str, int]
    disagreement_counts: dict[str, int]
    latest_window_end: datetime | None = None
    stale: bool


class MetricsSnapshot(BaseModel):
    """One polled snapshot of platform metrics. SSE relays this JSON
    verbatim -- it is the entire payload of the `snapshot` SSE event."""

    generated_at: datetime
    risingwave_connected: bool
    throughput: ThroughputMetrics | None = None
    faithfulness: FaithfulnessMetrics | None = None
    relevance: RelevanceMetrics | None = None
    tokens: TokenUsageMetrics | None = None
    cost: JudgeCostMetrics | None = None
    frontier: FrontierMetrics | None = None
