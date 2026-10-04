"""
Transition-audit emission for DriftController.

AuditedDriftController wraps a DriftController and answers "why did the
system disable its evaluator at 14:32?" with evidence -- a structured
TransitionRecord, logged and appended to CANARY_TRANSITIONS_PATH, emitted
only when record_result() actually changes the controller's sustained
state or operating mode, never on every observation.

The controller remains the sole authority: this wrapper never mutates its
hysteresis logic, it only compares current_state/current_mode before and
after a delegated record_result() call. The one thing the controller did
not already expose -- the entry/recovery streak counters -- was added as
two minimal read-only properties on DriftController itself (see
controller.py), not duplicated or recomputed here.

Known gap: DriftController.mark_operationally_unavailable()/
mark_operationally_available() are called directly on the controller, not
routed through this wrapper, so a transition caused by one of those calls
is only surfaced on the *next* audited record_result() -- by which point
current_state already reflects the override on both sides of the
before/after comparison, so no transition record is emitted for it. Wiring
those two calls through the wrapper too is straightforward if ever needed;
not done here because nothing in this phase calls them.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from finsentry.reliability.controller import DriftController, OperatingMode
from finsentry.reliability.health import JudgeHealthRecord, JudgeHealthState, LabeledResult

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CANARY_TRANSITIONS_PATH = _REPO_ROOT / "docs/measurements/reliability/canary_transitions.json"

TransitionReason = str  # one of: sustained_degradation, sustained_recovery,
# operationally_unavailable, insufficient_data, window_classification_change


@dataclass(frozen=True)
class TransitionRecord:
    observed_at: str | None
    previous_state: JudgeHealthState
    new_state: JudgeHealthState
    previous_mode: OperatingMode
    new_mode: OperatingMode
    window_n: int
    committed_n: int
    kappa: float | None
    entry_threshold: float
    recovery_threshold: float
    entry_streak: int
    recovery_streak: int
    judge_id: str
    reason: TransitionReason


def _reason(previous_state: JudgeHealthState, new_state: JudgeHealthState) -> TransitionReason:
    if new_state == "drifted":
        return "sustained_degradation"
    if new_state == "unavailable":
        return "operationally_unavailable"
    if new_state == "insufficient_data":
        return "insufficient_data"
    # new_state is healthy or degraded.
    if previous_state in ("drifted", "unavailable"):
        return "sustained_recovery"  # a genuine move out of a sustained/override state
    # A plain single-window classification change (insufficient_data's first
    # real verdict, or a healthy<->degraded mirror) that never crossed the
    # K/M hysteresis -- not "sustained" anything.
    return "window_classification_change"


def _append_transition(path: Path, transition: TransitionRecord) -> None:
    existing: list[dict[str, object]] = []
    if path.exists():
        existing = json.loads(path.read_text())
    existing.append(asdict(transition))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2))


class AuditedDriftController:
    """Observes a DriftController's record_result() calls and appends a
    TransitionRecord exactly when sustained state or operating mode changes."""

    def __init__(
        self,
        controller: DriftController,
        judge_id: str,
        transitions_path: Path = CANARY_TRANSITIONS_PATH,
    ) -> None:
        self._controller = controller
        self._judge_id = judge_id
        self._transitions_path = transitions_path

    @property
    def controller(self) -> DriftController:
        return self._controller

    def record_result(self, result: LabeledResult) -> JudgeHealthRecord:
        previous_state = self._controller.current_state
        previous_mode = self._controller.current_mode

        record = self._controller.record_result(result)

        new_state = self._controller.current_state
        new_mode = self._controller.current_mode
        if new_state == previous_state and new_mode == previous_mode:
            return record

        transition = TransitionRecord(
            observed_at=record.latest_observed_at,
            previous_state=previous_state,
            new_state=new_state,
            previous_mode=previous_mode,
            new_mode=new_mode,
            window_n=record.window_n,
            committed_n=record.committed_n,
            kappa=record.kappa,
            entry_threshold=record.entry_threshold,
            recovery_threshold=record.recovery_threshold,
            entry_streak=self._controller.entry_streak,
            recovery_streak=self._controller.recovery_streak,
            judge_id=self._judge_id,
            reason=_reason(previous_state, new_state),
        )
        log.info(
            "drift_transition judge_id=%s %s->%s mode=%s->%s reason=%s kappa=%s",
            self._judge_id,
            previous_state,
            new_state,
            previous_mode,
            new_mode,
            transition.reason,
            transition.kappa,
        )
        _append_transition(self._transitions_path, transition)
        return record
