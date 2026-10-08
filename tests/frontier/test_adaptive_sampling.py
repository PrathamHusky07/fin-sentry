"""Behavior of the lag-driven frontier sampling rate: it drops under sustained
backlog, recovers only after sustained relief, never flaps on a single reading,
and keeps the deterministic hash base at every rate. Synthetic lag sequences, no
Kafka, no model."""

from __future__ import annotations

import uuid

import pytest

from finsentry.frontier.sampling import (
    NORMAL_DENOMINATOR,
    REDUCED_DENOMINATOR,
    AdaptiveSamplingController,
    RateChange,
    should_sample_for_frontier,
)

# entry 100 / recovery 20 keeps the sequences short; the logic is threshold-agnostic.
HIGH, LOW, MID = 150, 5, 60


def _controller() -> AdaptiveSamplingController:
    return AdaptiveSamplingController(
        entry_lag=100, recovery_lag=20, entry_readings=3, recovery_readings=5
    )


def _feed(c: AdaptiveSamplingController, readings: list[int | None]) -> list[RateChange]:
    return [change for r in readings if (change := c.observe(r)) is not None]


def _reduced() -> AdaptiveSamplingController:
    c = _controller()
    _feed(c, [HIGH, HIGH, HIGH])
    assert c.denominator == REDUCED_DENOMINATOR
    return c


def test_starts_at_the_normal_rate() -> None:
    assert _controller().denominator == NORMAL_DENOMINATOR


def test_a_single_high_reading_does_not_change_the_rate() -> None:
    c = _controller()
    assert _feed(c, [HIGH]) == []
    assert c.denominator == NORMAL_DENOMINATOR


def test_sustained_lag_drops_the_rate_and_says_why() -> None:
    c = _controller()
    changes = _feed(c, [HIGH, HIGH, HIGH])
    assert c.denominator == REDUCED_DENOMINATOR
    assert len(changes) == 1
    assert changes[0].from_denominator == NORMAL_DENOMINATOR
    assert changes[0].to_denominator == REDUCED_DENOMINATOR
    assert changes[0].lag == HIGH
    assert "3 readings" in changes[0].reason


def test_an_interrupted_streak_never_reaches_entry() -> None:
    c = _controller()
    assert _feed(c, [HIGH, HIGH, MID, HIGH, HIGH, LOW, HIGH, HIGH]) == []
    assert c.denominator == NORMAL_DENOMINATOR


def test_recovery_needs_the_full_streak_of_low_readings() -> None:
    c = _reduced()
    assert _feed(c, [LOW] * 4) == []
    assert c.denominator == REDUCED_DENOMINATOR
    changes = _feed(c, [LOW])
    assert c.denominator == NORMAL_DENOMINATOR
    assert changes[0].to_denominator == NORMAL_DENOMINATOR
    assert "5 readings" in changes[0].reason


def test_one_low_reading_does_not_restore_the_rate() -> None:
    c = _reduced()
    assert _feed(c, [LOW, HIGH, LOW, HIGH, LOW]) == []
    assert c.denominator == REDUCED_DENOMINATOR


def test_the_band_between_the_thresholds_neither_restores_nor_progresses() -> None:
    c = _reduced()
    assert _feed(c, [LOW] * 4 + [MID] + [LOW] * 4) == []
    assert c.denominator == REDUCED_DENOMINATOR
    assert len(_feed(c, [LOW])) == 1


def test_alternating_readings_never_flap_the_rate() -> None:
    c = _controller()
    assert _feed(c, [HIGH, LOW] * 100) == []
    assert c.denominator == NORMAL_DENOMINATOR
    r = _reduced()
    assert _feed(r, [LOW, HIGH] * 100) == []
    assert r.denominator == REDUCED_DENOMINATOR


def test_an_unreadable_monitor_holds_the_rate_and_the_streak() -> None:
    c = _controller()
    assert _feed(c, [HIGH, HIGH, None, None]) == []
    assert c.denominator == NORMAL_DENOMINATOR
    assert len(_feed(c, [HIGH])) == 1  # the streak survived the gap
    r = _reduced()
    assert _feed(r, [None] * 20) == []
    assert r.denominator == REDUCED_DENOMINATOR


def test_a_full_cycle_logs_exactly_two_changes() -> None:
    c = _controller()
    changes = _feed(c, [HIGH] * 4 + [LOW] * 6)
    assert [x.to_denominator for x in changes] == [REDUCED_DENOMINATOR, NORMAL_DENOMINATOR]


def test_recovery_threshold_must_sit_below_entry() -> None:
    with pytest.raises(ValueError):
        AdaptiveSamplingController(entry_lag=100, recovery_lag=100)


def test_the_decision_at_a_rate_is_a_pure_function_of_the_trace_id() -> None:
    trace_id = str(uuid.uuid4())
    for denominator in (NORMAL_DENOMINATOR, REDUCED_DENOMINATOR):
        first = should_sample_for_frontier(trace_id, denominator)
        assert all(should_sample_for_frontier(trace_id, denominator) == first for _ in range(20))


def test_the_normal_rate_matches_the_original_ten_percent_hash() -> None:
    c = _controller()
    ids = [str(uuid.uuid4()) for _ in range(500)]
    assert [c.should_sample(t) for t in ids] == [should_sample_for_frontier(t) for t in ids]


def test_the_reduced_sample_is_a_subset_of_the_normal_sample() -> None:
    ids = [str(uuid.uuid4()) for _ in range(20_000)]
    normal = {t for t in ids if should_sample_for_frontier(t, NORMAL_DENOMINATOR)}
    reduced = {t for t in ids if should_sample_for_frontier(t, REDUCED_DENOMINATOR)}
    assert reduced <= normal
    assert 0.005 <= len(reduced) / len(ids) <= 0.015
    assert 0.09 <= len(normal) / len(ids) <= 0.11


def test_the_controller_applies_its_current_rate_to_the_decision() -> None:
    ids = [str(uuid.uuid4()) for _ in range(2_000)]
    c = _controller()
    at_normal = sum(c.should_sample(t) for t in ids)
    _feed(c, [HIGH] * 3)
    at_reduced = sum(c.should_sample(t) for t in ids)
    assert at_reduced < at_normal
