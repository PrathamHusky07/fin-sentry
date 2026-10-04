from __future__ import annotations

import math

import pytest

from finsentry.frontier.types import JudgeDecision
from finsentry.reliability.health import (
    DriftConfig,
    LabeledResult,
    compute_window_health,
)

_SMALL_CFG = DriftConfig(
    window_size=10,
    min_n=4,
    drift_entry_threshold=0.3,
    recovery_threshold=0.6,
    entry_consecutive_windows=2,
    recovery_consecutive_windows=3,
)


def _lr(decision: JudgeDecision, gold: bool) -> LabeledResult:
    return LabeledResult(decision=decision, gold_is_hallucination=gold)


def test_insufficient_data_below_min_n_even_with_perfect_committed_decisions() -> None:
    # 3 committed decisions, all correct (kappa would be 1.0) -- but
    # min_n=4, so state must be insufficient_data, not healthy.
    results = [
        _lr("refuted", True),
        _lr("supported", False),
        _lr("supported", False),
    ]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.state == "insufficient_data"
    assert record.committed_n == 3
    assert record.kappa == 1.0  # still reported as evidence, just not authoritative


def test_insufficient_data_when_committed_n_is_zero() -> None:
    results = [_lr("abstain", True), _lr("unavailable", False)]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.state == "insufficient_data"
    assert record.committed_n == 0
    assert record.kappa is None
    assert record.n_abstain == 1
    assert record.n_unavailable == 1


def test_healthy_when_kappa_at_or_above_recovery_threshold() -> None:
    # gold=[T,T,F,F], predicted via decision=[refuted,refuted,supported,supported]
    # -> perfect agreement, kappa=1.0 >= recovery_threshold=0.6.
    results = [
        _lr("refuted", True),
        _lr("refuted", True),
        _lr("supported", False),
        _lr("supported", False),
    ]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.state == "healthy"
    assert record.kappa is not None
    assert math.isclose(record.kappa, 1.0)
    assert record.committed_n == 4


def test_degraded_when_kappa_below_recovery_threshold() -> None:
    # gold=[T,T,F,F], predicted=[supported,refuted,refuted,supported]
    # (systematically backwards) -> kappa < 0, well below entry_threshold=0.3,
    # still just "degraded" at the single-window level (not "drifted" --
    # that requires sustained evidence from the hysteresis controller).
    results = [
        _lr("supported", True),
        _lr("refuted", True),
        _lr("refuted", False),
        _lr("supported", False),
    ]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.state == "degraded"
    assert record.kappa is not None and record.kappa < _SMALL_CFG.drift_entry_threshold


def test_degraded_in_the_middle_band_between_entry_and_recovery() -> None:
    # gold=[T,T,T,F,F,F], predicted=[refuted,refuted,supported,refuted,supported,supported]
    # 2 tp, 1 fn, 1 fp, 2 tn -> accuracy=4/6, chance-corrected kappa lands
    # strictly between 0.3 and 0.6 (verified by direct computation below,
    # not asserted against a hardcoded middle-band literal).
    results = [
        _lr("refuted", True),
        _lr("refuted", True),
        _lr("supported", True),
        _lr("refuted", False),
        _lr("supported", False),
        _lr("supported", False),
    ]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.kappa is not None
    assert _SMALL_CFG.drift_entry_threshold < record.kappa < _SMALL_CFG.recovery_threshold
    assert record.state == "degraded"


def test_abstain_and_unavailable_excluded_from_kappa_but_counted_as_evidence() -> None:
    results = [
        _lr("refuted", True),
        _lr("refuted", True),
        _lr("supported", False),
        _lr("supported", False),
        _lr("abstain", True),
        _lr("abstain", False),
        _lr("unavailable", True),
    ]
    record = compute_window_health(results, _SMALL_CFG)
    assert record.window_n == 7
    assert record.committed_n == 4
    assert record.n_abstain == 2
    assert record.n_unavailable == 1
    assert record.kappa is not None
    assert math.isclose(record.kappa, 1.0)  # unaffected by the excluded rows
    assert record.state == "healthy"


def test_drift_config_rejects_entry_threshold_not_below_recovery() -> None:
    with pytest.raises(ValueError, match="drift_entry_threshold"):
        DriftConfig(drift_entry_threshold=0.6, recovery_threshold=0.6)


def test_drift_config_rejects_recovery_streak_shorter_than_entry_streak() -> None:
    with pytest.raises(ValueError, match="recovery_consecutive_windows"):
        DriftConfig(entry_consecutive_windows=5, recovery_consecutive_windows=3)
