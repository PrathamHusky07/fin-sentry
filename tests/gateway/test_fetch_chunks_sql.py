"""
Regression test for the filing_date SQL typo (Day 8 Gate A). The ticker-less
branch of _fetch_chunks_sync had `filing_ date::text` (a stray space), which
every existing gateway test missed because all of them mock _fetch_chunks
entirely -- none exercise the real SQL string. These tests call the real
function against the real test-corpus table (no mocking) so a malformed
column list in either branch raises here, not silently in production.
"""

from __future__ import annotations

import os

from finsentry.gateway.main import _fetch_chunks_sync

_TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/finsentry_test",
)

_ZERO_EMBEDDING = [0.0] * 384


def test_fetch_chunks_ticker_less_branch_executes_against_real_corpus() -> None:
    """ticker=None must execute valid SQL against the real corpus table and
    return real filing_date values, not raise on a malformed column list."""
    chunks = _fetch_chunks_sync(_TEST_DATABASE_URL, _ZERO_EMBEDDING, None, 5)

    assert len(chunks) > 0
    assert all(c.filing_date != "" for c in chunks)


def test_fetch_chunks_ticker_branch_still_executes() -> None:
    """Sibling check: the ticker branch (already correct) keeps working so a
    future edit to one branch doesn't silently diverge from the other."""
    chunks = _fetch_chunks_sync(_TEST_DATABASE_URL, _ZERO_EMBEDDING, "AAPL", 5)

    assert len(chunks) > 0
    assert all(c.ticker == "AAPL" for c in chunks)
