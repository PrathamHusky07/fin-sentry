"""The gateway probe: its percentile math against hand-computed values, the all-or-nothing
failure behaviour, and the stored row against the test database."""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import psycopg
import pytest

from finsentry.observability.gateway_probe import (
    ROUTE,
    WARMUP_REQUESTS,
    ProbeFailedError,
    latest_summary,
    percentile,
    record_run,
    time_requests,
)

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finsentry_test"
)
_TARGET = "http://probe.test/health"


def test_percentile_matches_the_continuous_definition() -> None:
    # Rank 0.95 * 2 = 1.9 between 12200 and 29850: 12200 + 0.9 * 17650.
    assert percentile([29850, 3000, 12200], 0.95) == pytest.approx(28085.0)
    # Rank 0.95 * 4 = 3.8 between 4000 and 100000: 4000 + 0.8 * 96000.
    assert percentile([1000, 2000, 3000, 4000, 100000], 0.95) == pytest.approx(80800.0)
    assert percentile([1000, 2000, 3000, 4000, 100000], 0.5) == 3000
    assert percentile([18050], 0.95) == 18050


def test_percentile_of_nothing_is_an_error_not_zero() -> None:
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_time_requests_discards_the_warmup_and_times_every_other_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"status": "ok"})

    durations = time_requests("http://probe.test", 5, transport=httpx.MockTransport(handler))

    assert len(durations) == 5
    assert len(calls) == WARMUP_REQUESTS + 5
    assert set(calls) == {ROUTE}
    assert all(d >= 0 for d in durations)


def test_a_failing_request_aborts_the_run_with_no_figure() -> None:
    answered = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        answered["n"] += 1
        return httpx.Response(503 if answered["n"] == 4 else 200)

    with pytest.raises(ProbeFailedError):
        time_requests("http://probe.test", 10, transport=httpx.MockTransport(handler))


def test_an_unreachable_gateway_aborts_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProbeFailedError):
        time_requests("http://probe.test", 3, transport=httpx.MockTransport(handler))


@pytest.fixture
def empty_probe_table() -> Iterator[None]:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM gateway_probe_runs")
    yield
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM gateway_probe_runs")


@pytest.mark.usefixtures("empty_probe_table")
def test_summary_is_empty_before_any_run() -> None:
    summary = latest_summary(TEST_DATABASE_URL)
    assert summary.latest is None
    assert summary.runs_recorded == 0


@pytest.mark.usefixtures("empty_probe_table")
def test_recorded_run_is_stored_with_its_summary_and_read_back_newest_first() -> None:
    record_run(TEST_DATABASE_URL, _TARGET, [9.0, 11.0, 10.0])
    newest = record_run(TEST_DATABASE_URL, _TARGET, [3.0, 12.0, 30.0])

    summary = latest_summary(TEST_DATABASE_URL)

    assert summary.runs_recorded == 2
    assert summary.latest is not None
    assert summary.latest.measured_at == newest.measured_at
    assert summary.latest.samples == 3
    assert summary.latest.median_ms == 12.0
    assert summary.latest.p95_ms == pytest.approx(percentile([3.0, 12.0, 30.0], 0.95))
    assert summary.latest.max_ms == 30.0
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT latencies_ms FROM gateway_probe_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert sorted(row[0]) == [3.0, 12.0, 30.0]
