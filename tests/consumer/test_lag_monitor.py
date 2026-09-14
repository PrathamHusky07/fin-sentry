"""Tests for finsentry.consumer.lag_monitor.ConsumerLagMonitor."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from finsentry.consumer.lag_monitor import ConsumerLagMonitor, ConsumerLagReport, PartitionLag

_GROUP = "finsentry-rag-flash-judge"
_TOPIC = "rag-responses"

# Empirical rpk group describe --format json output from Redpanda v26.
_EMPIRICAL_JSON = json.dumps([
    {
        "group_name": _GROUP,
        "state": "Stable",
        "total_lag": 0,
        "partitions": [
            {
                "partition": 0,
                "current_offset": -1,
                "log_start_offset": 0,
                "log_end_offset": 0,
                "lag": 0,
                "topic": _TOPIC,
                "member_id": "aiokafka-0.14.0-mock",
                "client_id": "aiokafka-0.14.0",
                "host": "192.168.65.1",
            }
        ],
    }
])


def _make_monitor() -> ConsumerLagMonitor:
    return ConsumerLagMonitor(group_id=_GROUP, topic=_TOPIC)


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Blocking implementation tests (sync — no async overhead needed)
# ---------------------------------------------------------------------------


def test_fetch_lag_parses_rpk_output() -> None:
    """Happy path: empirical rpk JSON parses to one partition with zero lag."""
    with patch("subprocess.run", return_value=_completed(stdout=_EMPIRICAL_JSON)):
        report = _make_monitor()._fetch_lag_blocking()

    assert report.error is None
    assert len(report.partitions) == 1
    assert report.total_lag == 0


def test_fetch_lag_handles_fresh_consumer_negative_offset() -> None:
    """current_offset=-1 (fresh consumer) is clamped to 0, lag stays zero."""
    payload = json.dumps([{
        "group_name": _GROUP,
        "partitions": [{
            "partition": 0,
            "current_offset": -1,
            "log_end_offset": 0,
            "lag": 0,
            "topic": _TOPIC,
        }],
    }])
    with patch("subprocess.run", return_value=_completed(stdout=payload)):
        report = _make_monitor()._fetch_lag_blocking()

    assert report.partitions[0].committed_offset == 0
    assert report.partitions[0].lag == 0


def test_fetch_lag_returns_error_on_rpk_nonzero_exit() -> None:
    """Non-zero exit from rpk sets error field starting with 'rpk_exit_1'."""
    with patch("subprocess.run", return_value=_completed(returncode=1, stderr="group not found")):
        report = _make_monitor()._fetch_lag_blocking()

    assert report.ok is False
    assert report.error is not None
    assert report.error.startswith("rpk_exit_1")


def test_fetch_lag_returns_error_on_malformed_json() -> None:
    """Non-JSON stdout sets error field starting with 'parse_error'."""
    with patch("subprocess.run", return_value=_completed(stdout="not json")):
        report = _make_monitor()._fetch_lag_blocking()

    assert report.ok is False
    assert report.error is not None
    assert report.error.startswith("parse_error")


def test_fetch_lag_filters_to_configured_topic() -> None:
    """Partitions from unrelated topics are excluded from the report."""
    payload = json.dumps([{
        "group_name": _GROUP,
        "partitions": [
            {"partition": 0, "current_offset": 10, "log_end_offset": 20,
             "lag": 10, "topic": _TOPIC},
            {"partition": 0, "current_offset": 5, "log_end_offset": 15,
             "lag": 10, "topic": "something-else"},
        ],
    }])
    with patch("subprocess.run", return_value=_completed(stdout=payload)):
        report = _make_monitor()._fetch_lag_blocking()

    assert len(report.partitions) == 1
    assert report.partitions[0].topic == _TOPIC


# ---------------------------------------------------------------------------
# Pure-unit tests (no subprocess, no I/O)
# ---------------------------------------------------------------------------


def test_partition_lag_computes_correctly() -> None:
    p = PartitionLag(topic="t", partition=0, end_offset=100, committed_offset=80)
    assert p.lag == 20


def test_consumer_lag_report_total_lag_sums_partitions() -> None:
    report = ConsumerLagReport(
        group_id="g",
        partitions=[
            PartitionLag("t", 0, 100, 90),
            PartitionLag("t", 1, 200, 180),
        ],
    )
    assert report.total_lag == 30
