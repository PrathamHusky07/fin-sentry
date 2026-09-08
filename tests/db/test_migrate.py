from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest

from finsentry.db import migrate

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finsentry")

_VALID_SQL = "CREATE TABLE IF NOT EXISTS _test_migrate_dummy (id TEXT PRIMARY KEY);"
_BAD_SQL = "THIS IS NOT VALID SQL;"


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    yield
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE filename LIKE '_test_%'")
        conn.execute("DROP TABLE IF EXISTS _test_migrate_dummy")


def test_first_run_applies_migration_and_records_it(tmp_path: Path) -> None:
    (tmp_path / "_test_001_valid.sql").write_text(_VALID_SQL)

    with patch.object(migrate, "MIGRATIONS_DIR", tmp_path):
        migrate.run(DATABASE_URL)

    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT filename FROM schema_migrations WHERE filename = %s",
            ("_test_001_valid.sql",),
        ).fetchone()
    assert row is not None
    assert row[0] == "_test_001_valid.sql"


def test_second_run_applies_nothing(tmp_path: Path) -> None:
    (tmp_path / "_test_001_valid.sql").write_text(_VALID_SQL)

    with patch.object(migrate, "MIGRATIONS_DIR", tmp_path):
        migrate.run(DATABASE_URL)
        migrate.run(DATABASE_URL)

    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT filename FROM schema_migrations WHERE filename = %s",
            ("_test_001_valid.sql",),
        ).fetchall()
    assert len(rows) == 1


def test_bad_sql_rolls_back_and_leaves_no_record(tmp_path: Path) -> None:
    (tmp_path / "_test_002_bad.sql").write_text(_BAD_SQL)

    with patch.object(migrate, "MIGRATIONS_DIR", tmp_path):
        with pytest.raises(Exception):
            migrate.run(DATABASE_URL)

    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s",
            ("_test_002_bad.sql",),
        ).fetchone()
    assert row is None
