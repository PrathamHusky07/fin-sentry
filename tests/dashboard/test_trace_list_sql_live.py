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

from finsentry.dashboard.app import _dao, _fetch_disagreement_trace_ids, _fetch_trace_list


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
    discipline as the test above."""
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
        assert all(r["judge_state"] == "evaluated" for r in rows)

        rows = await _fetch_trace_list(
            limit=5, offset=0, ticker=None, rag_status=None, frontier_sampled=True
        )
        assert _dao.last_query_failed is False
        assert all(r["frontier_sampled"] is True for r in rows)

        rows = await _fetch_trace_list(
            limit=5, offset=0, ticker=None, rag_status=None, disagreement=True
        )
        assert _dao.last_query_failed is False
        assert isinstance(rows, list)
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
