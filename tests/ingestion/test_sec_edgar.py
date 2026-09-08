from __future__ import annotations

import os

import psycopg
import pytest

from finsentry.ingestion.sec_edgar import ingest
from tests.conftest import TEST_DATABASE_URL

# A small AAPL subset keeps wall-clock time reasonable while still hitting the real SEC.
_AAPL_SPEC = {"10-K": 1, "10-Q": 1, "8-K": 3}
_EXPECTED_FILING_COUNTS = {"10-K": 1, "10-Q": 1, "8-K": 3}

_EXPECTED_COLUMNS = {
    "id",
    "ticker",
    "filing_type",
    "accession_number",
    "filing_date",
    "period_of_report",
    "chunk_index",
    "chunk_text",
    "chunk_tokens",
    "embedding",
    "source_url",
    "created_at",
}


def _require_identity() -> None:
    if not os.getenv("EDGAR_IDENTITY"):
        pytest.skip("EDGAR_IDENTITY not set — SEC EDGAR tests require a real identity header")


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    _require_identity()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE corpus")
    ingest(TEST_DATABASE_URL, tickers=["AAPL"], filing_spec=_AAPL_SPEC)


def test_row_count_and_filing_structure() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        total = conn.execute("SELECT COUNT(*) FROM corpus WHERE ticker = 'AAPL'").fetchone()
        assert total is not None
        assert total[0] > 0, "Expected at least one chunk for AAPL"

        for form_type, expected_count in _EXPECTED_FILING_COUNTS.items():
            filing_count = conn.execute(
                "SELECT COUNT(DISTINCT accession_number) FROM corpus "
                "WHERE ticker = 'AAPL' AND filing_type = %s",
                (form_type,),
            ).fetchone()
            assert filing_count is not None
            assert filing_count[0] == expected_count, (
                f"Expected {expected_count} {form_type} filing(s), got {filing_count[0]}"
            )

        min_chunks = conn.execute(
            "SELECT MIN(cnt) FROM ("
            "  SELECT accession_number, COUNT(*) AS cnt FROM corpus"
            "  WHERE ticker = 'AAPL' GROUP BY accession_number"
            ") sub"
        ).fetchone()
        assert min_chunks is not None
        assert min_chunks[0] > 1, "Expected more than one chunk per filing"

        bad_embeddings = conn.execute(
            "SELECT COUNT(*) FROM corpus WHERE ticker = 'AAPL' "
            "AND vector_dims(embedding) != 384"
        ).fetchone()
        assert bad_embeddings is not None
        assert bad_embeddings[0] == 0, "All embeddings must be 384-dimensional"


def test_schema_and_pgvector_extension() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'corpus'"
        ).fetchall()
        actual_columns = {r[0] for r in rows}
        assert actual_columns == _EXPECTED_COLUMNS

        col_types = {r[0]: r[1] for r in rows}
        assert col_types["embedding"] == "USER-DEFINED", (
            "pgvector column reports as USER-DEFINED in information_schema"
        )

        ext = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        ).fetchone()
        assert ext is not None
        assert ext[0] is True, "pgvector extension must be installed"


def test_idempotent_reingest() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM corpus WHERE ticker = 'AAPL'").fetchone()
    assert count_before is not None

    ingest(TEST_DATABASE_URL, tickers=["AAPL"], filing_spec=_AAPL_SPEC)

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        count_after = conn.execute("SELECT COUNT(*) FROM corpus WHERE ticker = 'AAPL'").fetchone()
    assert count_after is not None
    assert count_after[0] == count_before[0], "Second ingest must not add rows"
