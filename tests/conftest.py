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


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-topic-tests",
        action="store_true",
        default=False,
        help=(
            "Also run the tests marked live_topics. They publish a successful event to the "
            "live rag-responses topic, which the running flash consumer judges with a real "
            "Gemini call."
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-topic-tests"):
        return
    skip = pytest.mark.skip(
        reason="publishes to the live topics, where a consumer pays for a judge call "
        "(pass --run-live-topic-tests to run it)"
    )
    for item in items:
        if "live_topics" in item.keywords:
            item.add_marker(skip)
