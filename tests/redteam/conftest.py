from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from finsentry.redteam.run_gate import PASSWORD_ENV, run_gate
from tests.conftest import TEST_DATABASE_URL

# A throwaway value that exists only in the test process. It is not the real run password.
TEST_RUN_PASSWORD = "test-run-password"


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


@pytest.fixture(autouse=True)
def _run_gate_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with the gate configured and with no failed attempts on record."""
    monkeypatch.setenv(PASSWORD_ENV, TEST_RUN_PASSWORD)
    run_gate.reset()
    yield
    run_gate.reset()
