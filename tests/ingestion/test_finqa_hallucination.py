from __future__ import annotations

import os

import psycopg
import pytest

from finsentry.db.migrate import run as run_migrations
from finsentry.ingestion.finqa_hallucination import ingest

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finsentry")

_EXPECTED_SCHEMA = {
    "id": "text",
    "question": "text",
    "context": "text",
    "response": "text",
    "is_hallucination": "boolean",
    "source": "text",
    "created_at": "timestamp with time zone",
}


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    run_migrations(DATABASE_URL)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE hallucination_bench")
    ingest(DATABASE_URL)


def test_row_count() -> None:
    # Source has 1657 rows but 6 pairs share identical (query, llm_response) with the same label.
    # Content-hash deduplication via ON CONFLICT DO NOTHING yields 1651 unique records.
    with psycopg.connect(DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM hallucination_bench").fetchone()
    assert result is not None
    assert result[0] == 1651


def test_schema_columns_and_types() -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'hallucination_bench'"
        ).fetchall()
    actual = {r[0]: r[1] for r in rows}
    assert actual == _EXPECTED_SCHEMA


def test_idempotent_reingest() -> None:
    ingest(DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM hallucination_bench").fetchone()
    assert result is not None
    assert result[0] == 1651
