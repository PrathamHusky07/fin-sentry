from __future__ import annotations

import psycopg
import pytest

from finsentry.ingestion.finqa_hallucination import EXPECTED_RECORD_COUNT, ingest
from tests.conftest import TEST_DATABASE_URL

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
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE hallucination_bench")
    ingest(TEST_DATABASE_URL)


def test_row_count() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM hallucination_bench").fetchone()
    assert result is not None
    assert result[0] == EXPECTED_RECORD_COUNT


def test_schema_columns_and_types() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'hallucination_bench'"
        ).fetchall()
    actual = {r[0]: r[1] for r in rows}
    assert actual == _EXPECTED_SCHEMA


def test_idempotent_reingest() -> None:
    ingest(TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM hallucination_bench").fetchone()
    assert result is not None
    assert result[0] == EXPECTED_RECORD_COUNT
