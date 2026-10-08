"""Offset-commit invariants of RagEventConsumer.

The commit for a partition may only move to the end of the unbroken run of finished
messages. Finishing a message is not the same as being allowed to commit it.

Offsets in assertions are Kafka "next to read" values: finishing offset 101 makes 102
the commit target.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from aiokafka import TopicPartition

from finsentry.consumer.rag_event_consumer import RagEventConsumer, _OffsetTracker
from finsentry.events.schema import RagResponseEvent
from tests.consumer.test_rag_event_consumer import _make_consumer, _make_event, _make_kafka_msg

TP0 = TopicPartition("rag-responses", 0)
TP1 = TopicPartition("rag-responses", 1)


# ---------------------------------------------------------------------------
# The tracker on its own: pure bookkeeping, no event loop
# ---------------------------------------------------------------------------


def _tracker(*offsets: int, tp: tuple[str, int] = ("t", 0)) -> _OffsetTracker:
    tracker = _OffsetTracker()
    for offset in offsets:
        tracker.register(tp, offset)
    return tracker


def test_tracker_ordered_completion_advances_one_at_a_time() -> None:
    tracker = _tracker(100, 101, 102)
    tp = ("t", 0)
    for done, target in [(100, 101), (101, 102), (102, 103)]:
        tracker.complete(tp, done)
        assert tracker.commit_target(tp) == target


def test_tracker_out_of_order_completion_stops_at_the_gap() -> None:
    """100 done, 101 done, 102 pending, 103 done, 104 done: commit 101, not 104."""
    tracker = _tracker(100, 101, 102, 103, 104)
    tp = ("t", 0)
    for done in (100, 101, 103, 104):
        tracker.complete(tp, done)
    assert tracker.commit_target(tp) == 102  # next to read after 101
    tracker.complete(tp, 102)
    assert tracker.commit_target(tp) == 105  # the gap closed, everything is eligible


def test_tracker_nothing_is_eligible_while_the_first_message_is_pending() -> None:
    tracker = _tracker(100, 101)
    tracker.complete(("t", 0), 101)
    assert tracker.commit_target(("t", 0)) is None


def test_tracker_failed_message_holds_the_frontier_then_releases_it() -> None:
    """101 fails (never completes) while 102 and 103 finish. The frontier stays at 100.
    When 101 later succeeds, 102 and 103 become eligible with no further completion."""
    tracker = _tracker(100, 101, 102, 103)
    tp = ("t", 0)
    tracker.complete(tp, 100)
    tracker.complete(tp, 102)
    tracker.complete(tp, 103)
    assert tracker.commit_target(tp) == 101
    tracker.mark_committed(tp, 101)
    assert tracker.commit_target(tp) is None  # still held by 101
    tracker.complete(tp, 101)
    assert tracker.commit_target(tp) == 104


def test_tracker_partitions_are_independent() -> None:
    tracker = _OffsetTracker()
    tracker.register(("t", 0), 5)
    tracker.register(("t", 1), 7)
    tracker.register(("t", 1), 8)
    tracker.complete(("t", 1), 7)
    tracker.complete(("t", 1), 8)
    assert tracker.commit_target(("t", 0)) is None
    assert tracker.commit_target(("t", 1)) == 9


def test_tracker_offset_gaps_in_the_log_do_not_block_the_frontier() -> None:
    """Transaction markers and compaction leave holes in the offset sequence. The
    frontier follows the registered messages, not offset arithmetic."""
    tracker = _tracker(100, 105)
    tracker.complete(("t", 0), 100)
    tracker.complete(("t", 0), 105)
    assert tracker.commit_target(("t", 0)) == 106


def test_tracker_a_commit_that_did_not_land_stays_the_target() -> None:
    tracker = _tracker(100)
    tracker.complete(("t", 0), 100)
    assert tracker.commit_target(("t", 0)) == 101
    assert tracker.commit_target(("t", 0)) == 101  # nothing was marked committed
    tracker.mark_committed(("t", 0), 101)
    assert tracker.commit_target(("t", 0)) is None


def test_tracker_redelivery_below_the_frontier_is_ignored() -> None:
    tracker = _tracker(100, 101)
    tracker.complete(("t", 0), 100)
    tracker.complete(("t", 0), 101)
    tracker.mark_committed(("t", 0), 102)
    tracker.register(("t", 0), 100)  # redelivered after a rebalance
    tracker.complete(("t", 0), 100)
    assert tracker.commit_target(("t", 0)) is None


# ---------------------------------------------------------------------------
# The consumer loop with real concurrency
# ---------------------------------------------------------------------------


def _msgs(offsets: list[int], partition: int = 0) -> list[Any]:
    events = [_make_event(app_trace_id=f"trace-{partition}-{o}") for o in offsets]
    return [_make_kafka_msg(e.model_dump(), o, partition) for e, o in zip(events, offsets)]


def _record_commits(consumer: RagEventConsumer) -> list[dict[TopicPartition, int]]:
    commits: list[dict[TopicPartition, int]] = []

    async def _commit(offsets: dict[TopicPartition, int]) -> None:
        commits.append(dict(offsets))

    consumer._consumer.commit.side_effect = _commit  # type: ignore[attr-defined]
    return commits


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def _offset_of(ev: RagResponseEvent) -> int:
    return int(ev.app_trace_id.rsplit("-", 1)[1])


@pytest.mark.anyio
async def test_consumer_ordered_completion_commits_each_next_offset() -> None:
    consumer = _make_consumer(_msgs([100, 101, 102]), max_concurrency=1)
    commits = _record_commits(consumer)

    async def _handler(ev: RagResponseEvent) -> None:
        return None

    consumer.set_handler(_handler)
    await consumer.start()
    await consumer.run()

    assert commits == [{TP0: 101}, {TP0: 102}, {TP0: 103}]


@pytest.mark.anyio
async def test_consumer_out_of_order_completion_commits_only_the_contiguous_frontier() -> None:
    """100 and 101 finish, 102 is still running, 103 and 104 finish. The commit stays
    at 102 (next to read after 101). When 102 finishes it jumps to 105. Handlers still
    run concurrently, so correctness did not cost parallelism."""
    consumer = _make_consumer(_msgs([100, 101, 102, 103, 104]))
    commits = _record_commits(consumer)
    release_102 = asyncio.Event()
    running = 0
    peak = 0

    async def _handler(ev: RagResponseEvent) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        if _offset_of(ev) == 102:
            await release_102.wait()
        running -= 1

    consumer.set_handler(_handler)
    await consumer.start()
    run = asyncio.create_task(consumer.run())
    await _settle()

    assert commits and commits[-1] == {TP0: 102}
    assert all(c[TP0] <= 102 for c in commits)

    release_102.set()
    await asyncio.wait_for(run, timeout=2)
    assert commits[-1] == {TP0: 105}
    assert peak > 1


@pytest.mark.anyio
async def test_consumer_failed_handler_never_lets_the_commit_pass_it() -> None:
    """101 fails every attempt. 100 is committed, 102 and 103 are processed, and the
    commit never moves beyond 101 (next to read after 100)."""
    consumer = _make_consumer(_msgs([100, 101, 102, 103]), max_attempts=2)
    commits = _record_commits(consumer)
    calls: list[int] = []

    async def _handler(ev: RagResponseEvent) -> None:
        calls.append(_offset_of(ev))
        if _offset_of(ev) == 101:
            raise RuntimeError("downstream down")

    consumer.set_handler(_handler)
    await consumer.start()
    await consumer.run()

    assert calls.count(101) == 2
    assert calls.count(102) == 1 and calls.count(103) == 1
    assert commits == [{TP0: 101}]


@pytest.mark.anyio
async def test_consumer_gap_recovery_commits_completed_followers_without_reprocessing() -> None:
    """101 fails its first attempt while 102 and 103 finish. The frontier holds at 100.
    The retry of 101 succeeds, and 102 and 103 become eligible without being run again."""
    consumer = _make_consumer(_msgs([100, 101, 102, 103]), max_attempts=3)
    commits = _record_commits(consumer)
    followers_done = asyncio.Event()
    calls: list[int] = []
    finished = 0

    async def _handler(ev: RagResponseEvent) -> None:
        nonlocal finished
        offset = _offset_of(ev)
        calls.append(offset)
        if offset == 101 and calls.count(101) == 1:
            await followers_done.wait()
            raise RuntimeError("transient")
        if offset in (102, 103):
            finished += 1
            if finished == 2:
                followers_done.set()

    consumer.set_handler(_handler)
    await consumer.start()
    await asyncio.wait_for(consumer.run(), timeout=2)

    assert calls.count(101) == 2
    assert calls.count(102) == 1 and calls.count(103) == 1
    assert commits[0] == {TP0: 101}  # held at 100 while 101 was failing
    assert all(c[TP0] <= 101 for c in commits[:1])
    assert commits[-1] == {TP0: 104}  # released once 101 succeeded


@pytest.mark.anyio
async def test_consumer_invalid_message_advances_only_in_order() -> None:
    """A garbage message between two valid ones is dropped. It cannot be committed
    past the still-running 100, and it does not hold anything back afterwards."""
    messages = [
        _msgs([100])[0],
        _make_kafka_msg(b"not-json", offset=101),
        _msgs([102])[0],
    ]
    consumer = _make_consumer(messages)
    commits = _record_commits(consumer)
    release_100 = asyncio.Event()

    async def _handler(ev: RagResponseEvent) -> None:
        if _offset_of(ev) == 100:
            await release_100.wait()

    consumer.set_handler(_handler)
    await consumer.start()
    run = asyncio.create_task(consumer.run())
    await _settle()

    assert commits == []  # 100 is pending, so neither 101 nor 102 is eligible

    release_100.set()
    await asyncio.wait_for(run, timeout=2)
    assert commits[-1] == {TP0: 103}


@pytest.mark.anyio
async def test_consumer_commit_failure_is_logged_and_retried_on_the_next_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The commit for 100 fails. 101 is still running when 102 finishes, so 102 does
    not move the frontier, yet it must still retry the commit that failed."""
    consumer = _make_consumer(_msgs([100, 101, 102]))
    landed: list[dict[TopicPartition, int]] = []
    release_101 = asyncio.Event()
    attempts = 0

    async def _commit(offsets: dict[TopicPartition, int]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("broker rejected the commit")
        landed.append(dict(offsets))

    consumer._consumer.commit.side_effect = _commit  # type: ignore[attr-defined]

    async def _handler(ev: RagResponseEvent) -> None:
        if _offset_of(ev) == 101:
            await release_101.wait()

    consumer.set_handler(_handler)
    await consumer.start()
    with caplog.at_level(logging.ERROR, logger="finsentry.consumer.rag_event_consumer"):
        run = asyncio.create_task(consumer.run())
        await _settle()
        assert any("Commit failed" in r.message for r in caplog.records)
        assert landed == [{TP0: 101}]  # 102 retried the failed commit, frontier still at 100
        release_101.set()
        await asyncio.wait_for(run, timeout=2)

    assert landed[-1] == {TP0: 103}


@pytest.mark.anyio
async def test_consumer_partitions_commit_independently() -> None:
    """Partition 0 is blocked on offset 5. Partition 1 finishes 7 and 8 and commits,
    and nothing is committed for partition 0."""
    messages = [*_msgs([5], partition=0), *_msgs([7, 8], partition=1)]
    consumer = _make_consumer(messages)
    commits = _record_commits(consumer)
    release = asyncio.Event()

    async def _handler(ev: RagResponseEvent) -> None:
        if ev.app_trace_id == "trace-0-5":
            await release.wait()

    consumer.set_handler(_handler)
    await consumer.start()
    run = asyncio.create_task(consumer.run())
    await _settle()

    assert commits[-1] == {TP1: 9}
    assert all(TP0 not in c for c in commits)

    release.set()
    await asyncio.wait_for(run, timeout=2)
    assert commits[-1] == {TP0: 6}


@pytest.mark.anyio
async def test_consumer_concurrency_never_exceeds_the_cap_with_commit_tracking() -> None:
    cap = 3
    consumer = _make_consumer(_msgs(list(range(20))), max_concurrency=cap)
    _record_commits(consumer)
    running = 0
    peak = 0

    async def _handler(ev: RagResponseEvent) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.001 * (20 - _offset_of(ev)))  # later offsets finish first
        running -= 1

    consumer.set_handler(_handler)
    await consumer.start()
    await asyncio.wait_for(consumer.run(), timeout=5)

    assert 1 < peak <= cap
