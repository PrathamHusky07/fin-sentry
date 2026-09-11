"""Tests for finsentry.consumer.lag_monitor.ConsumerLagMonitor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from finsentry.consumer.lag_monitor import ConsumerLagMonitor, ConsumerLagReport, PartitionLag


def _make_monitor() -> ConsumerLagMonitor:
    return ConsumerLagMonitor(
        admin_url="http://redpanda:9644",
        group_id="finsentry-rag-flash-judge",
        topic="rag-responses",
    )


def _mock_client(json_response: object, status_code: int = 200) -> AsyncMock:
    resp = MagicMock()
    resp.json.return_value = json_response
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )

    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.anyio
async def test_fetch_lag_returns_report_with_total_lag() -> None:
    """Happy path: admin API returns two partitions, total_lag is sum."""
    payload = [
        {"partition_id": 0, "end_offset": 1000, "committed_offset": 950},
        {"partition_id": 1, "end_offset": 500, "committed_offset": 500},
    ]
    monitor = _make_monitor()
    monitor.inject_http_client(_mock_client(payload))

    report = await monitor.fetch_lag()

    assert isinstance(report, ConsumerLagReport)
    assert report.ok is True
    assert report.total_lag == 50
    assert len(report.partitions) == 2


@pytest.mark.anyio
async def test_fetch_lag_total_lag_never_negative() -> None:
    """committed_offset > end_offset (can happen after compaction) clips to zero."""
    payload = [{"partition_id": 0, "end_offset": 10, "committed_offset": 20}]
    monitor = _make_monitor()
    monitor.inject_http_client(_mock_client(payload))

    report = await monitor.fetch_lag()

    assert report.total_lag == 0
    assert report.partitions[0].lag == 0


@pytest.mark.anyio
async def test_fetch_lag_http_error_returns_error_report() -> None:
    """HTTP 404 from admin API returns a ConsumerLagReport with error set."""
    monitor = _make_monitor()
    monitor.inject_http_client(_mock_client({}, status_code=404))

    report = await monitor.fetch_lag()

    assert report.ok is False
    assert report.error is not None
    assert report.total_lag == 0


@pytest.mark.anyio
async def test_fetch_lag_network_error_returns_error_report() -> None:
    """Network failure returns a ConsumerLagReport with error set."""
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    monitor = _make_monitor()
    monitor.inject_http_client(client)

    report = await monitor.fetch_lag()

    assert report.ok is False
    assert report.error is not None


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
