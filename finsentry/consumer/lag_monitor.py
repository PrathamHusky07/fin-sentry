"""
Consumer lag monitor: shells to rpk group describe for consumer group lag.

The lag is the number of messages in the topic that the consumer group has
not yet processed. A growing lag means the FlashJudge consumer is falling
behind the gateway's publish rate.

Uses docker exec to call rpk inside the finsentry-redpanda container.
Redpanda's HTTP Admin API does not expose consumer group offsets; shelling to
rpk group describe is the correct approach and matches the established pattern
in scripts/init_risingwave.py::_ensure_topics.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

from finsentry.events.topics import DEFAULT_CONSUMER_GROUP, RAG_RESPONSES_TOPIC

log = logging.getLogger(__name__)


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
    """Shells to rpk group describe for consumer group lag.

    Runs rpk via docker exec so no host-side Kafka tooling is required.
    """

    def __init__(
        self,
        group_id: str = "finsentry-rag-flash-judge",
        topic: str = "rag-responses",
        container: str = "finsentry-redpanda",
    ) -> None:
        self._group_id = group_id
        self._topic = topic
        self._container = container

    async def fetch_lag(self) -> ConsumerLagReport:
        """Fetch current consumer group lag by shelling to `rpk group describe`.

        Runs in a thread executor so subprocess.run does not block the event loop.
        Returns a ConsumerLagReport; on rpk failure, report.error is set and
        report.partitions is empty.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_lag_blocking)

    def _fetch_lag_blocking(self) -> ConsumerLagReport:
        try:
            result = subprocess.run(
                [
                    "docker", "exec", self._container,
                    "rpk", "group", "describe", self._group_id, "--format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return ConsumerLagReport(group_id=self._group_id, error="timeout")
        except FileNotFoundError:
            return ConsumerLagReport(group_id=self._group_id, error="docker_not_found")

        if result.returncode != 0:
            return ConsumerLagReport(
                group_id=self._group_id,
                error=f"rpk_exit_{result.returncode}: {result.stderr.strip()[:200]}",
            )

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return ConsumerLagReport(group_id=self._group_id, error=f"parse_error: {exc}")

        return self._parse_response(payload)

    def _parse_response(self, data: Any) -> ConsumerLagReport:
        try:
            # rpk group describe returns a list of group descriptors
            descriptor = data[0] if isinstance(data, list) else data
            raw_partitions = descriptor.get("partitions", [])
            partitions: list[PartitionLag] = []
            for item in raw_partitions:
                if item.get("topic") != self._topic:
                    continue
                partitions.append(
                    PartitionLag(
                        topic=self._topic,
                        partition=item.get("partition", 0),
                        end_offset=item.get("log_end_offset", 0),
                        committed_offset=max(0, item.get("current_offset", 0)),
                    )
                )
        except (TypeError, KeyError, AttributeError, IndexError) as exc:
            return ConsumerLagReport(group_id=self._group_id, error=f"parse_error: {exc}")
        return ConsumerLagReport(group_id=self._group_id, partitions=partitions)


def lag_monitor_from_env() -> ConsumerLagMonitor:
    return ConsumerLagMonitor(
        group_id=os.getenv("KAFKA_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP),
        topic=os.getenv("KAFKA_TOPIC", RAG_RESPONSES_TOPIC),
    )
