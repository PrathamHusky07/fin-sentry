from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _clean_red_team_tables() -> Iterator[None]:
    """Each test starts and ends with empty red team tables in the test database."""

    def wipe() -> None:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM red_team_executions")
            conn.execute("DELETE FROM red_team_runs")

    wipe()
    yield
    wipe()
