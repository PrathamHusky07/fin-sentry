"""
AuditedDriftController proves it emits a transition record exactly when the
controller's sustained state or operating mode changes -- not on every
observation. All sequences are synthetic LabeledResults, no live Gemini call.
"""

from __future__ import annotations

import json
from pathlib import Path

from finsentry.reliability.audit import AuditedDriftController
from finsentry.reliability.controller import DriftController
from finsentry.reliability.health import DriftConfig, LabeledResult

_T0 = "2026-01-01T00:00:00+00:00"

# entry_consecutive_windows=1: the first breaching window flips sustained_state
# straight to "drifted" (skipping the "degraded" mirror), so driving to drift
# is exactly one audited transition, not two. recovery_consecutive_windows=2
# keeps the first recovery-grade window from flipping state immediately (sticky),
# so recovery is also exactly one audited transition, on the 2nd good window.
_CFG = DriftConfig(
    window_size=1,
    min_n=1,
    drift_entry_threshold=0.3,
    recovery_threshold=0.6,
    entry_consecutive_windows=1,
    recovery_consecutive_windows=2,
)

_GOOD = LabeledResult(decision="refuted", gold_is_hallucination=True, observed_at=_T0)
_BAD = LabeledResult(decision="supported", gold_is_hallucination=True, observed_at=_T0)


def test_healthy_to_drifted_to_recovered_emits_exactly_two_transitions(tmp_path: Path) -> None:
    transitions_path = tmp_path / "canary_transitions.json"
    controller = DriftController(_CFG)
    controller.record_result(_GOOD)  # establish healthy baseline, not through the audit layer
    assert controller.current_state == "healthy"

    audited = AuditedDriftController(
        controller, judge_id="gemini-rubric", transitions_path=transitions_path
    )

    audited.record_result(_BAD)  # 1st breach, K=1 -> drifted immediately
    assert controller.current_state == "drifted"

    audited.record_result(_GOOD)  # recovery_streak=1 < M=2 -- stays drifted, sticky
    assert controller.current_state == "drifted"

    audited.record_result(_GOOD)  # recovery_streak=2 == M=2 -> healthy
    assert controller.current_state == "healthy"

    records = json.loads(transitions_path.read_text())
    assert len(records) == 2

    first, second = records
    assert first["previous_state"] == "healthy"
    assert first["new_state"] == "drifted"
    assert first["previous_mode"] == "normal"
    assert first["new_mode"] == "frontier_only"
    assert first["reason"] == "sustained_degradation"
    assert first["judge_id"] == "gemini-rubric"
    assert first["entry_streak"] == 1

    assert second["previous_state"] == "drifted"
    assert second["new_state"] == "healthy"
    assert second["previous_mode"] == "frontier_only"
    assert second["new_mode"] == "normal"
    assert second["reason"] == "sustained_recovery"
    assert second["recovery_streak"] == 0  # reset to 0 the moment recovery completes


def test_no_transition_record_when_state_and_mode_unchanged(tmp_path: Path) -> None:
    transitions_path = tmp_path / "canary_transitions.json"
    controller = DriftController(_CFG)
    controller.record_result(_GOOD)
    audited = AuditedDriftController(
        controller, judge_id="gemini-rubric", transitions_path=transitions_path
    )

    audited.record_result(_GOOD)  # still healthy, still normal -- no transition
    audited.record_result(_GOOD)

    assert not transitions_path.exists()
