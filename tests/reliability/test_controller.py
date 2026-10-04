"""
Synthetic failure/recovery tests for DriftController. These prove the
state-machine's *behavior* across sequences of windowed readings (hysteresis
holding, sustained-drift confirmation, stricter recovery), not just that
compute_window_health's arithmetic is correct in isolation (that is
test_health.py's job). All sequences below are synthetic kappa/label
sequences -- no live Gemini call anywhere in this file.
"""
from __future__ import annotations

from finsentry.reliability.controller import DriftController, OperatingMode
from finsentry.reliability.health import DriftConfig, JudgeHealthState, LabeledResult

_T0 = "2026-01-01T00:00:00+00:00"


def _state(controller: DriftController) -> JudgeHealthState:
    """Reads current_state through a function call rather than a bare
    attribute access repeated across statements -- mypy's literal narrowing
    otherwise treats repeated `controller.current_state` expressions as
    statically fixed to whatever an earlier `==` assert narrowed them to,
    even across intervening state-mutating calls, producing spurious
    'non-overlapping equality check' errors under --strict."""
    return controller.current_state


def _mode(controller: DriftController) -> OperatingMode:
    return controller.current_mode


# Shared across the window_size=3 scenarios: HEALTHY_ITEM/BAD_ITEM share the
# same gold label (True) and differ only in decision, so the kappa of any
# mix of them is governed purely by how many of the window's 3 slots are
# "correct" -- verified concretely in the assertions below, not assumed.
# These fixtures are deliberately single-gold-class (gold is always True):
# they exercise the controller's breach/no-breach streak boundary, not
# kappa gradation across a realistic label mix -- do not mistake them for
# statistically representative windows.
# always correct
_HEALTHY_ITEM = LabeledResult(decision="refuted", gold_is_hallucination=True, observed_at=_T0)
# always wrong (FN)
_BAD_ITEM = LabeledResult(decision="supported", gold_is_hallucination=True, observed_at=_T0)

# gold=[T,T,F], predicted=[T,F,F] (middle item is a false negative) -> kappa=0.4
# (hand-derivation in docs/build-log.md's Day 6 Phase 0 entry's method; here
# verified empirically by the assertion in test_recovery_requires_clearing_the_stricter_margin).
_MIDDLE_BATCH = [
    LabeledResult(decision="refuted", gold_is_hallucination=True, observed_at=_T0),
    LabeledResult(decision="supported", gold_is_hallucination=True, observed_at=_T0),
    LabeledResult(decision="supported", gold_is_hallucination=False, observed_at=_T0),
]

_CFG_W3 = DriftConfig(
    window_size=3,
    min_n=3,
    drift_entry_threshold=0.3,
    recovery_threshold=0.6,
    entry_consecutive_windows=2,
    recovery_consecutive_windows=3,
)

_CFG_W1 = DriftConfig(
    window_size=1,
    min_n=1,
    drift_entry_threshold=0.3,
    recovery_threshold=0.6,
    entry_consecutive_windows=3,
    recovery_consecutive_windows=5,
)


def test_transitions_to_drifted_after_exactly_k_windows_not_before() -> None:
    controller = DriftController(_CFG_W3)
    for _ in range(3):
        record = controller.record_result(_HEALTHY_ITEM)
    assert record.state == "healthy"
    assert _mode(controller) == "normal"

    # 1st breach: window=[H,H,B], kappa=0.0 (<=0.3) -- entry_streak=1 < K=2.
    record = controller.record_result(_BAD_ITEM)
    assert record.kappa == 0.0
    assert _state(controller) == "degraded"
    assert _mode(controller) == "normal"  # NOT drifted yet

    # 2nd consecutive breach: window=[H,B,B], kappa=0.0 -- entry_streak=2 == K.
    record = controller.record_result(_BAD_ITEM)
    assert record.kappa == 0.0
    assert _state(controller) == "drifted"
    assert _mode(controller) == "frontier_only"


def test_single_noisy_window_inside_healthy_stream_does_not_transition() -> None:
    controller = DriftController(_CFG_W1)

    # correct -> kappa=1.0
    r1 = controller.record_result(LabeledResult("refuted", True, observed_at=_T0))
    assert r1.kappa == 1.0
    assert _state(controller) == "healthy"
    assert _mode(controller) == "normal"

    # one noisy breach -- wrong -> kappa=0.0
    r2 = controller.record_result(LabeledResult("supported", True, observed_at=_T0))
    assert r2.kappa == 0.0
    assert _state(controller) == "degraded"
    assert _mode(controller) == "normal"  # still not drifted -- K=3 needed

    # back to healthy immediately -- hysteresis must hold, no transition occurred
    # correct -> kappa=1.0
    r3 = controller.record_result(LabeledResult("refuted", True, observed_at=_T0))
    assert r3.kappa == 1.0
    assert _state(controller) == "healthy"
    assert _mode(controller) == "normal"


def test_recovery_requires_m_consecutive_windows_stricter_than_entry() -> None:
    controller = DriftController(_CFG_W1)
    good = LabeledResult("refuted", True, observed_at=_T0)
    bad = LabeledResult("supported", True, observed_at=_T0)

    # Drive to drifted (K=3 consecutive breaches).
    for _ in range(3):
        controller.record_result(bad)
    assert _state(controller) == "drifted"
    assert _mode(controller) == "frontier_only"

    # M=5 required; feed only 4 consecutive recovery-grade windows -- must
    # stay drifted (sticky), proving M is enforced and not satisfied early.
    for i in range(4):
        record = controller.record_result(good)
        assert record.kappa == 1.0
        assert _state(controller) == "drifted", f"recovered too early at window {i + 1}"
        assert _mode(controller) == "frontier_only"

    # 5th consecutive recovery-grade window -- now it recovers.
    record = controller.record_result(good)
    assert record.kappa == 1.0
    assert _state(controller) == "healthy"
    assert _mode(controller) == "normal"


def test_recovery_requires_clearing_the_stricter_margin_not_merely_improving() -> None:
    """Proves recovery is a stricter bar than entry, not just "no longer
    breaching": a window that is clearly better than the drift-causing
    windows (kappa=0.4 vs. the 0.0 that caused drift) but still below the
    0.6 recovery_threshold must NOT advance recovery, and must NOT lift the
    drifted state -- only a window that clears 0.6 counts."""
    controller = DriftController(_CFG_W3)
    for _ in range(3):
        controller.record_result(_HEALTHY_ITEM)
    for _ in range(2):  # K=2 -> drifted
        controller.record_result(_BAD_ITEM)
    assert _state(controller) == "drifted"

    # Inject the middle-band batch one item at a time; after all three, the
    # window is exactly _MIDDLE_BATCH (maxlen=3 flushes everything prior).
    record = None
    for item in _MIDDLE_BATCH:
        record = controller.record_result(item)
    assert record is not None and record.kappa is not None
    assert 0.3 < record.kappa < 0.6  # strictly between entry and recovery
    assert _state(controller) == "drifted"  # still drifted -- margin not cleared
    assert _mode(controller) == "frontier_only"

    # Now genuinely recover: M=3 consecutive clearly-above-recovery windows.
    # The first _HEALTHY_ITEM feed still has one _MIDDLE_BATCH item in the
    # window (maxlen=3 slides by one), reproducing the same middle-band
    # kappa=0.4 one more tick before the window is purely healthy -- so it
    # takes 4 feeds, not 3, for 3 *consecutive* recovery-grade windows.
    record = controller.record_result(_HEALTHY_ITEM)
    assert record.kappa is not None
    assert 0.3 < record.kappa < 0.6
    assert _state(controller) == "drifted"  # still not recovered
    for _ in range(3):
        record = controller.record_result(_HEALTHY_ITEM)
    assert record.kappa == 1.0
    assert _state(controller) == "healthy"
    assert _mode(controller) == "normal"


def test_insufficient_data_while_window_below_min_n_claims_neither_healthy_nor_drifted() -> None:
    cfg = DriftConfig(
        window_size=5,
        min_n=4,
        drift_entry_threshold=0.3,
        recovery_threshold=0.6,
        entry_consecutive_windows=2,
        recovery_consecutive_windows=3,
    )
    controller = DriftController(cfg)
    good = LabeledResult("refuted", True, observed_at=_T0)

    for i in range(3):  # committed_n will be 1, 2, 3 -- all < min_n=4
        record = controller.record_result(good)
        assert record.state == "insufficient_data", f"tick {i + 1}"
        assert _state(controller) == "insufficient_data"
        assert _mode(controller) == "normal"

    # 4th labeled item: committed_n=4 == min_n -- now a real verdict.
    record = controller.record_result(good)
    assert record.state == "healthy"
    assert _state(controller) == "healthy"


def test_mark_operationally_unavailable_overrides_kappa_derived_state() -> None:
    controller = DriftController(_CFG_W1)
    controller.record_result(LabeledResult("refuted", True, observed_at=_T0))
    assert _state(controller) == "healthy"

    controller.mark_operationally_unavailable()
    assert _state(controller) == "unavailable"
    assert _mode(controller) == "frontier_only"

    controller.mark_operationally_available()
    assert _state(controller) == "healthy"  # kappa-derived state unaffected underneath
    assert _mode(controller) == "normal"
