from __future__ import annotations

import os

import pytest

from finsentry.db.migrate import run as run_migrations

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/finsentry_test",
)


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    run_migrations(TEST_DATABASE_URL)
