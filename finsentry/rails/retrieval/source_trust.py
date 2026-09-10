"""
Deterministic source-trust check for retrieved chunks.

No ML. Pure invariant validation against the known corpus contract:
  - chunk_id must exist in the corpus table.
  - ticker must be in the known 10-company set.
  - filing_type must be in {"10-K", "10-Q", "8-K"}.
  - filing_date, if non-empty, must parse as an ISO date.
  - source_url, if non-empty, must begin with https://www.sec.gov/.

Any failure drops the chunk. Fail-open per chunk (not per request): a single
untrusted chunk does not fail the entire retrieval response.
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# The ten companies in the SEC EDGAR demo corpus.
_KNOWN_TICKERS: frozenset[str] = frozenset(
    ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "JPM", "BRK-B", "TSLA", "WMT"]
)

_KNOWN_FILING_TYPES: frozenset[str] = frozenset(["10-K", "10-Q", "8-K"])

_SEC_URL_RE: re.Pattern[str] = re.compile(r"^https://www\.sec\.gov/")


def check_chunk(
    chunk_id: str,
    ticker: str,
    filing_type: str,
    filing_date: str,
    source_url: str,
    db_conn: Any,
) -> tuple[bool, str]:
    """Validate a single chunk against the source-trust invariants.

    Returns (trusted, reason). reason is the failure description on False,
    empty string on True.

    db_conn must be an open psycopg connection. Caller is responsible for
    connection lifecycle.
    """
    if ticker not in _KNOWN_TICKERS:
        return False, f"unknown ticker {ticker!r}"

    if filing_type not in _KNOWN_FILING_TYPES:
        return False, f"unknown filing_type {filing_type!r}"

    if filing_date:
        try:
            datetime.date.fromisoformat(filing_date)
        except ValueError:
            return False, f"malformed filing_date {filing_date!r}"

    if source_url and not _SEC_URL_RE.match(source_url):
        return False, f"source_url does not begin with https://www.sec.gov/: {source_url!r}"

    with db_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM corpus WHERE id = %s LIMIT 1", (chunk_id,))
        if cur.fetchone() is None:
            return False, f"chunk_id {chunk_id!r} not found in corpus"

    return True, ""
