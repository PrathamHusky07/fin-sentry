"""
Day 9 Phase 0 regression test. The trace-list SQL (a LEFT JOIN from
rag_events to judge_verdicts, plus a separate `app_trace_id = ANY(%s)`
array-parameter query against rag_frontier_verdicts) was only ever exercised
through tests/dashboard/test_trace_routes.py, which mocks
_fetch_all/_fetch_one -- the real SQL string had never executed against
RisingWave's streaming query planner before Phase 0. Manual verification
(see docs/build-log.md) ran both queries by hand against the live instance
and confirmed they succeed; this test makes that an ongoing regression
check, following the same no-mock discipline as
tests/gateway/test_fetch_chunks_sql.py (the Day 8 filing_date test) against
the real database rather than a fake cursor.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

from finsentry.dashboard.app import _dao, _fetch_disagreement_trace_ids, _fetch_trace_list
from finsentry.events.schema import JudgeVerdictEvent, RagResponseEvent
from finsentry.events.topics import JUDGE_VERDICTS_TOPIC, RAG_RESPONSES_TOPIC

_BOOTSTRAP = "localhost:19092"


async def _publish(topic: str, payload: bytes) -> None:
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=_BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=payload)
    finally:
        await producer.stop()


async def test_fetch_trace_list_executes_against_real_risingwave() -> None:
    """Real LEFT JOIN + ORDER BY + LIMIT/OFFSET, then a real `= ANY(%s)`
    array-parameter query, against the live RisingWave instance -- no
    mocking. A planner rejection of either query shape raises or flips
    last_query_failed here, not silently behind fetch_all's
    swallow-and-return-empty contract."""
    await _dao.open()
    try:
        assert _dao.connected, "RisingWave not reachable -- start docker-compose.dev.yml"

        rows = await _fetch_trace_list(limit=5, offset=0, ticker=None, rag_status=None)

        assert _dao.last_query_failed is False
        assert isinstance(rows, list)
    finally:
        await _dao.close()


async def test_fetch_trace_list_search_and_filter_params_execute_against_real_risingwave() -> None:
    """Day 9 Session 2A: the Investigations search/filter extensions
    (ILIKE search, judge_state translation, frontier_sampled membership,
    disagreement-id filter) against the live instance -- same no-mock
    discipline as the test above.

    Day 9 Session 2B strengthening: the judge_state="evaluated" and
    frontier_sampled=True assertions below originally used `all(...)`,
    which is vacuously true on an empty result set -- they would still pass
    if the filter silently returned nothing. Both are snapshot assertions
    (not structural invariants): today's live data has at least one
    evaluated trace and at least one frontier-sampled trace (confirmed via
    direct query at the time this was written -- see docs/build-log.md), so
    a non-empty check plus the `all(...)` population check together prove
    the filter both runs and returns the correct population, not just the
    correct population of nothing."""
    await _dao.open()
    try:
        assert _dao.connected, "RisingWave not reachable -- start docker-compose.dev.yml"

        rows = await _fetch_trace_list(limit=5, offset=0, ticker=None, rag_status=None, q="amazon")
        assert _dao.last_query_failed is False
        assert isinstance(rows, list)

        rows = await _fetch_trace_list(
            limit=5, offset=0, ticker=None, rag_status=None, judge_state="evaluated"
        )
        assert _dao.last_query_failed is False
        assert len(rows) > 0, "snapshot assertion: expected at least one evaluated trace today"
        assert all(r["judge_state"] == "evaluated" for r in rows)

        # Every public judge_state filter must plan and execute in RisingWave and return
        # only rows the classifier labels with that same state.
        for state in (
            "never_evaluated",
            "evaluated",
            "partially_evaluated",
            "blocked_before_evaluation",
            "judge_failed",
        ):
            rows = await _fetch_trace_list(
                limit=5, offset=0, ticker=None, rag_status=None, judge_state=state
            )
            assert _dao.last_query_failed is False, state
            assert all(r["judge_state"] == state for r in rows), state

        rows = await _fetch_trace_list(
            limit=5, offset=0, ticker=None, rag_status=None, frontier_sampled=True
        )
        assert _dao.last_query_failed is False
        assert len(rows) > 0, (
            "snapshot assertion: expected at least one frontier-sampled trace today"
        )
        assert all(r["frontier_sampled"] is True for r in rows)

        rows = await _fetch_trace_list(
            limit=5, offset=0, ticker=None, rag_status=None, disagreement=True
        )
        assert _dao.last_query_failed is False
        assert isinstance(rows, list)
    finally:
        await _dao.close()


async def test_fetch_trace_list_picks_latest_judge_verdict_when_trace_has_two_rows() -> None:
    """Day 9 Session 2B duplicate-row fix. judge_verdicts is an append-only
    RisingWave source over the judge-verdicts Kafka topic (see
    infra/risingwave/init.sql) -- nothing prevents a retried/re-scored
    evaluation from producing a second verdict row for the same
    app_trace_id, which Session 2B's corpus and later experiments will
    exercise. The plain LEFT JOIN this test guards against would fan this
    out into two duplicate rows in the list with an arbitrary judge_status
    each; the fix (a ROW_NUMBER() OVER (PARTITION BY app_trace_id ORDER BY
    timestamp_utc DESC) window, finsentry/dashboard/app.py) must return
    exactly one row, carrying the state of the later verdict -- the same
    row _fetch_trace_detail's ORDER BY timestamp_utc DESC LIMIT 1 would
    pick. Publishes real events to the real Kafka topics (no synthetic DB
    insert) and polls RisingWave for them to materialize."""
    app_trace_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    rag_event = RagResponseEvent(
        event_id=str(uuid.uuid4()),
        app_trace_id=app_trace_id,
        timestamp_utc=now.isoformat(),
        status="success",
        endpoint="/v1/rag/query",
        query=f"duplicate-verdict regression probe {app_trace_id}",
        ticker="AAPL",
        retrieved_chunk_ids=["chunk-1"],
        retrieved_chunks_text=["Total net sales were $391,035 million."],
        answer="Total net sales were $391,035 million.",
        citations=[{"chunk_id": "chunk-1", "quote": "$391,035 million"}],
        total_latency_ms=100,
    )
    older_verdict = JudgeVerdictEvent(
        event_id=str(uuid.uuid4()),
        source_event_id=rag_event.event_id,
        app_trace_id=app_trace_id,
        timestamp_utc=(now - timedelta(seconds=30)).isoformat(),
        status="partial",
        faithfulness_status="skipped_evaluator_error",
        answer_relevance_score=0.8,
        answer_relevance_status="complete",
        context_relevance_status="skipped_evaluator_error",
    )
    latest_verdict = JudgeVerdictEvent(
        event_id=str(uuid.uuid4()),
        source_event_id=rag_event.event_id,
        app_trace_id=app_trace_id,
        timestamp_utc=now.isoformat(),
        status="complete",
        faithfulness_score=1.0,
        faithfulness_status="complete",
        answer_relevance_score=0.9,
        answer_relevance_status="complete",
        context_relevance_score=0.9,
        context_relevance_status="complete",
    )

    await _publish(RAG_RESPONSES_TOPIC, rag_event.to_kafka_json())
    await _publish(JUDGE_VERDICTS_TOPIC, older_verdict.to_kafka_json())
    await _publish(JUDGE_VERDICTS_TOPIC, latest_verdict.to_kafka_json())

    await _dao.open()
    try:
        assert _dao.connected, "RisingWave not reachable -- start docker-compose.dev.yml"

        deadline = time.monotonic() + 20.0
        rows: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            rows = await _fetch_trace_list(
                limit=10, offset=0, ticker=None, rag_status=None, q=app_trace_id
            )
            if rows:
                break
            await asyncio.sleep(1.0)

        assert len(rows) == 1, (
            f"expected exactly one row for a trace with two judge_verdicts rows, got {len(rows)}"
        )
        assert rows[0]["app_trace_id"] == app_trace_id
        assert rows[0]["judge_state"] == "evaluated"  # the later ("complete") verdict won
    finally:
        await _dao.close()


async def test_disagreement_trace_ids_finds_the_real_amazon_hallucination_trace() -> None:
    """The real cross-tier disagreement in today's data: flash scored
    trace 96bca4b5-f707-4a93-b421-2674032849b5 (AMZN FY2024 net income)
    1.0/complete; the real gemini-rubric frontier judge scored it 0.0,
    catching a hallucination flash missed (see docs/build-log.md and
    docs/internal/day9-frontend-data-contract.md). This is a snapshot
    assertion against live, mutable data -- it documents a specific known
    trace rather than a structural invariant, so it's expected to need an
    update if that trace is ever purged from RisingWave."""
    await _dao.open()
    try:
        assert _dao.connected, "RisingWave not reachable -- start docker-compose.dev.yml"

        disagreement_ids = await _fetch_disagreement_trace_ids()

        assert "96bca4b5-f707-4a93-b421-2674032849b5" in disagreement_ids
    finally:
        await _dao.close()
