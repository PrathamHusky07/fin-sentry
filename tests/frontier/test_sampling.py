from __future__ import annotations

import uuid

from finsentry.frontier.sampling import sampling_key, should_sample_for_frontier


def test_same_trace_id_always_produces_same_decision() -> None:
    trace_id = str(uuid.uuid4())
    first = should_sample_for_frontier(trace_id)
    for _ in range(50):
        assert should_sample_for_frontier(trace_id) == first


def test_approximately_ten_percent_rate_across_10000_uuids() -> None:
    trace_ids = [str(uuid.uuid4()) for _ in range(10_000)]
    sampled_count = sum(1 for t in trace_ids if should_sample_for_frontier(t))

    rate = sampled_count / len(trace_ids)
    assert 0.09 <= rate <= 0.11


def test_different_trace_ids_can_produce_different_decisions() -> None:
    trace_ids = [str(uuid.uuid4()) for _ in range(100)]
    decisions = {should_sample_for_frontier(t) for t in trace_ids}

    assert decisions == {True, False}


def test_sampling_key_is_the_app_trace_id() -> None:
    trace_id = "some-trace-id"
    assert sampling_key(trace_id) == trace_id
