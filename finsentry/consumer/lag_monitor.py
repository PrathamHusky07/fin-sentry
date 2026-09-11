"""
Consumer lag monitor: polls Redpanda Admin API for consumer group lag.

The lag (end_offset - committed_offset) is the number of messages in the
topic that the consumer group has not yet processed. A growing lag means
the FlashJudge consumer is falling behind the gateway's publish rate.

Uses the Redpanda HTTP Admin API (port 9644 by default). No Kafka protocol
needed — this is a lightweight HTTP GET.

Returned by GET /admin/partitions?group=<group> on the Redpanda admin port.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_ADMIN_URL = "http://localhost:9644"


@dataclass
class PartitionLag:
    topic: str
    partition: int
    end_offset: int
    committed_offset: int

    @property
    def lag(self) -> int:
        return max(0, self.end_offset - self.committed_offset)


@dataclass
class ConsumerLagReport:
    group_id: str
    partitions: list[PartitionLag] = field(default_factory=list)
    error: str | None = None

    @property
    def total_lag(self) -> int:
        return sum(p.lag for p in self.partitions)

    @property
    def ok(self) -> bool:
        return self.error is None


class ConsumerLagMonitor:
    """Polls Redpanda Admin API for consumer group lag.

    inject_http_client() replaces the underlying httpx client for unit tests.
    """

    def __init__(
        self,
        admin_url: str = _DEFAULT_ADMIN_URL,
        group_id: str = "finsentry-rag-flash-judge",
        topic: str = "rag-responses",
    ) -> None:
        self._admin_url = admin_url.rstrip("/")
        self._group_id = group_id
        self._topic = topic
        self._client: Any = None

    def inject_http_client(self, client: Any) -> None:
        """Inject a pre-built httpx.AsyncClient for testing."""
        self._client = client

    async def fetch_lag(self) -> ConsumerLagReport:
        """Fetch current consumer group lag from the Redpanda Admin API."""
        import httpx

        client = self._client
        close_after = client is None

        if client is None:
            client = httpx.AsyncClient(timeout=5.0)

        try:
            url = f"{self._admin_url}/v1/kafka/groups/{self._group_id}/topics/{self._topic}/offsets"
            resp = await client.get(url)
            resp.raise_for_status()
            return self._parse_response(resp.json())
        except httpx.HTTPStatusError as exc:
            log.warning("ConsumerLagMonitor: HTTP error %s for group %s", exc.response.status_code, self._group_id)
            return ConsumerLagReport(group_id=self._group_id, error=f"http_{exc.response.status_code}")
        except Exception as exc:
            log.warning("ConsumerLagMonitor: request failed — %s", exc)
            return ConsumerLagReport(group_id=self._group_id, error=str(exc))
        finally:
            if close_after:
                await client.aclose()

    def _parse_response(self, data: Any) -> ConsumerLagReport:
        partitions: list[PartitionLag] = []
        try:
            for item in data:
                partition_id = item.get("partition_id", 0)
                end_offset = item.get("end_offset", 0)
                committed_offset = item.get("committed_offset", 0)
                partitions.append(
                    PartitionLag(
                        topic=self._topic,
                        partition=partition_id,
                        end_offset=end_offset,
                        committed_offset=committed_offset,
                    )
                )
        except (TypeError, KeyError, AttributeError) as exc:
            return ConsumerLagReport(group_id=self._group_id, error=f"parse_error: {exc}")
        return ConsumerLagReport(group_id=self._group_id, partitions=partitions)


def lag_monitor_from_env() -> ConsumerLagMonitor:
    return ConsumerLagMonitor(
        admin_url=os.getenv("REDPANDA_ADMIN_URL", _DEFAULT_ADMIN_URL),
        group_id=os.getenv("KAFKA_CONSUMER_GROUP", "finsentry-rag-flash-judge"),
        topic=os.getenv("KAFKA_TOPIC", "rag-responses"),
    )
