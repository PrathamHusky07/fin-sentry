from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from tests.conftest import TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _clean_investigation_tables() -> Iterator[None]:
    """Each test starts and ends with empty investigation tables in the test database."""

    def wipe() -> None:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM investigation_events")
            conn.execute("DELETE FROM investigations")

    wipe()
    yield
    wipe()
