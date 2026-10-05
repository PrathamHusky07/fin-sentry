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

from finsentry.dashboard.app import _dao, _fetch_trace_list


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
