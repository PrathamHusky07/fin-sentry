"""The request-latency SQL, run against the real RisingWave with known latencies.

mv_request_throughput_1m stored an APPROX_PERCENTILE sketch that returned a lower-rank value on
a small bucket: requests of 3000, 12200 and 29850 ms reported a p95 of 12213 ms under a mean of
15017 ms. These tests run the actual statements from infra/risingwave/init.sql and the dashboard
reader over scratch tables, so a wrong percentile function or a join that mixes row sets fails
here against inputs whose true answers are computed by hand. The scratch objects are dropped
afterwards and no product stream, topic or table is touched.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from finsentry.dashboard.app import _THROUGHPUT_COLUMNS, _THROUGHPUT_SOURCE
from finsentry.risingwave.dao import risingwave_dsn

_INIT_SQL = Path(__file__).resolve().parents[2] / "infra" / "risingwave" / "init.sql"

# Latencies in ms, one list per minute bucket, with the true mean and the continuous
# 95th percentile (linear interpolation at rank 0.95 * (n - 1)) worked out by hand.
_SMALL_BUCKET = [3000, 12200, 29850]  # mean 15016.67, p95 = 12200 + 0.9 * 17650 = 28085
_SKEWED_BUCKET = [1000, 2000, 3000, 4000, 100000]  # mean 22000, p95 = 4000 + 0.8 * 96000 = 80800
_SINGLE_BUCKET = [18050]  # mean 18050, p95 18050

_MINUTES = {
    "2026-01-01 00:01:00+00": _SMALL_BUCKET,
    "2026-01-01 00:02:00+00": _SKEWED_BUCKET,
    "2026-01-01 00:03:00+00": _SINGLE_BUCKET,
}


def _exact_view_sql(view: str, table: str) -> str:
    """The init.sql statement that defines mv_request_latency_exact_1m, aimed at a scratch table."""
    text = _INIT_SQL.read_text()
    match = re.search(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS mv_request_latency_exact_1m AS.*?;",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, "init.sql no longer defines mv_request_latency_exact_1m"
    return match.group(0).replace("mv_request_latency_exact_1m", view).replace("rag_events", table)


@pytest.fixture
def scratch() -> Iterator[tuple[psycopg.Connection, str]]:
    """A connection and a unique name suffix; every object created with it is dropped after."""
    suffix = uuid.uuid4().hex[:8]
    try:
        conn = psycopg.connect(risingwave_dsn(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("RisingWave is not reachable")
    try:
        yield conn, suffix
    finally:
        for stmt in (
            f"DROP MATERIALIZED VIEW IF EXISTS scratch_exact_{suffix}",
            f"DROP TABLE IF EXISTS scratch_standin_exact_{suffix}",
            f"DROP TABLE IF EXISTS scratch_legacy_{suffix}",
            f"DROP TABLE IF EXISTS scratch_events_{suffix}",
        ):
            conn.execute(stmt)
        conn.close()


def _seed_events(conn: psycopg.Connection, suffix: str) -> str:
    table = f"scratch_events_{suffix}"
    conn.execute(f"CREATE TABLE {table} (timestamp_utc TIMESTAMPTZ, total_latency_ms INT)")
    for minute, latencies in _MINUTES.items():
        for i, ms in enumerate(latencies):
            ts = minute.replace(":00+00", f":{10 + i * 5}+00")
            conn.execute(f"INSERT INTO {table} VALUES (%s, %s)", (ts, ms))
    conn.execute("FLUSH")
    return table


def test_exact_view_reports_the_true_average_and_95th_percentile(
    scratch: tuple[psycopg.Connection, str],
) -> None:
    conn, suffix = scratch
    table = _seed_events(conn, suffix)
    conn.execute(_exact_view_sql(f"scratch_exact_{suffix}", table))
    conn.execute("FLUSH")

    rows = conn.execute(
        f"SELECT window_start, request_count, avg_latency_ms, p95_latency_ms "
        f"FROM scratch_exact_{suffix} ORDER BY window_start"
    ).fetchall()

    assert [r[1] for r in rows] == [3, 5, 1]
    expected = [
        (Decimal("15016.67"), 28085.0),
        (Decimal("22000"), 80800.0),
        (Decimal("18050"), 18050.0),
    ]
    for (_, _, avg, p95), (want_avg, want_p95) in zip(rows, expected, strict=True):
        assert abs(Decimal(avg) - want_avg) < Decimal("0.01")
        assert abs(float(p95) - want_p95) < 0.5
        # Sanity only: with at most 20 requests a continuous p95 is not below the mean.
        assert float(p95) >= float(avg)


def test_reader_gives_p95_only_where_the_exact_view_counted_the_same_rows(
    scratch: tuple[psycopg.Connection, str],
) -> None:
    """Stand-in tables take the two view names. The legacy bucket has three requests. The exact
    side matches it for minute 1, undercounts it for minute 2 (events the topic had expired by the
    time the exact view was built), and has no row for minute 3."""
    conn, suffix = scratch
    legacy, exact = f"scratch_legacy_{suffix}", f"scratch_standin_exact_{suffix}"
    conn.execute(
        f"CREATE TABLE {legacy} (window_start TIMESTAMPTZ, window_end TIMESTAMPTZ, "
        "total_requests BIGINT, success_count BIGINT, blocked_count BIGINT, error_count BIGINT, "
        "avg_latency_ms DOUBLE PRECISION, p95_latency_ms DOUBLE PRECISION)"
    )
    conn.execute(
        f"CREATE TABLE {exact} (window_start TIMESTAMPTZ, request_count BIGINT, "
        "avg_latency_ms DOUBLE PRECISION, p95_latency_ms DOUBLE PRECISION)"
    )
    for minute, end in (
        ("2026-01-01 00:01:00+00", "2026-01-01 00:02:00+00"),
        ("2026-01-01 00:02:00+00", "2026-01-01 00:03:00+00"),
        ("2026-01-01 00:03:00+00", "2026-01-01 00:04:00+00"),
    ):
        # The legacy p95 is the below-the-mean sketch value, which the reader must never return.
        conn.execute(
            f"INSERT INTO {legacy} VALUES (%s, %s, 3, 3, 0, 0, 15016.7, 12213.1)", (minute, end)
        )
    conn.execute(f"INSERT INTO {exact} VALUES ('2026-01-01 00:01:00+00', 3, 15016.7, 28085.0)")
    conn.execute(f"INSERT INTO {exact} VALUES ('2026-01-01 00:02:00+00', 2, 9000.0, 11000.0)")
    conn.execute("FLUSH")

    source = _THROUGHPUT_SOURCE.replace("mv_request_throughput_1m", legacy).replace(
        "mv_request_latency_exact_1m", exact
    )
    rows = conn.execute(
        f"SELECT l.window_start, ROUND(l.avg_latency_ms::numeric, 1), "
        f"ROUND(e.p95_latency_ms::numeric, 1) FROM {source} ORDER BY l.window_start"
    ).fetchall()

    assert [r[2] for r in rows] == [Decimal("28085.0"), None, None]
    assert rows[0][2] >= rows[0][1]


def test_reader_column_list_names_the_fields_the_snapshot_expects() -> None:
    for name in (
        "total_requests",
        "success_count",
        "blocked_count",
        "error_count",
        "avg_latency_ms",
        "p95_latency_ms",
        "window_start",
        "window_end",
    ):
        assert name in _THROUGHPUT_COLUMNS
