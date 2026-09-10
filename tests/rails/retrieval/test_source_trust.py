"""
Contract tests for finsentry.rails.retrieval.source_trust.check_chunk.

All tests are deterministic. No model downloads, no real DB connections.
The DB lookup is covered by a mock psycopg connection.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from finsentry.rails.retrieval.source_trust import check_chunk


def _make_conn(found: bool) -> MagicMock:
    """Mock psycopg connection that returns a row iff found=True."""
    cur = MagicMock()
    cur.fetchone.return_value = (1,) if found else None
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def _good_conn() -> MagicMock:
    return _make_conn(found=True)


def _kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "chunk_id": "abc123",
        "ticker": "AAPL",
        "filing_type": "10-K",
        "filing_date": "2024-09-28",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/test.htm",
        "db_conn": _good_conn(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_source_trust_valid_metadata_passes() -> None:
    """Known ticker, valid filing_type, ISO filing_date, valid SEC URL, chunk in DB."""
    trusted, reason = check_chunk(**_kwargs())
    assert trusted is True
    assert reason == ""


def test_source_trust_empty_source_url_passes() -> None:
    """Empty source_url is explicitly allowed — corpus without URL data still passes."""
    trusted, reason = check_chunk(**_kwargs(source_url=""))
    assert trusted is True
    assert reason == ""


def test_source_trust_empty_filing_date_passes() -> None:
    """Empty filing_date is allowed — the date check only runs when non-empty."""
    trusted, reason = check_chunk(**_kwargs(filing_date=""))
    assert trusted is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------


def test_source_trust_invalid_ticker_drops() -> None:
    """Ticker not in the 10-company set is rejected."""
    trusted, reason = check_chunk(**_kwargs(ticker="XYZ"))
    assert trusted is False
    assert "ticker" in reason.lower()


def test_source_trust_invalid_filing_type_drops() -> None:
    """Filing type outside {10-K, 10-Q, 8-K} is rejected."""
    trusted, reason = check_chunk(**_kwargs(filing_type="10-K/A"))
    assert trusted is False
    assert "filing_type" in reason.lower()


def test_source_trust_malformed_filing_date_drops() -> None:
    """Non-ISO filing_date string is rejected."""
    trusted, reason = check_chunk(**_kwargs(filing_date="not-a-date"))
    assert trusted is False
    assert "filing_date" in reason.lower()


def test_source_trust_non_sec_url_drops() -> None:
    """source_url not beginning with https://www.sec.gov/ is rejected."""
    trusted, reason = check_chunk(**_kwargs(source_url="https://malicious.com/x"))
    assert trusted is False
    assert "source_url" in reason.lower()


def test_source_trust_nonexistent_chunk_id_drops() -> None:
    """chunk_id not found in corpus table is rejected."""
    conn = _make_conn(found=False)
    trusted, reason = check_chunk(**_kwargs(db_conn=conn))
    assert trusted is False
    assert "chunk_id" in reason.lower()
