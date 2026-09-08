from __future__ import annotations

import psycopg
import pytest

from finsentry.ingestion.financebench import ingest
from tests.conftest import TEST_DATABASE_URL

_EXPECTED_COLUMNS = {"id", "question", "expected_answer", "doc_id", "source", "created_at"}


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE golden_set")
    ingest(TEST_DATABASE_URL)


def test_row_count() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM golden_set").fetchone()
    assert result is not None
    assert result[0] == 150


def test_schema_has_expected_columns() -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'golden_set'"
        ).fetchall()
    assert {r[0] for r in rows} == _EXPECTED_COLUMNS


def test_idempotent_reingest() -> None:
    ingest(TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        result = conn.execute("SELECT COUNT(*) FROM golden_set").fetchone()
    assert result is not None
    assert result[0] == 150
