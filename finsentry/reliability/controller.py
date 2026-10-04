"""
DriftController: stateful hysteresis over a sequence of windowed judge-health
readings, plus the rolling window buffer itself.

Owns two things compute_window_health (finsentry/reliability/health.py) does
not: the rolling buffer of recent LabeledResults (a maxlen deque, so "window"
means the same thing on every call without the caller re-slicing a list), and
the entry/recovery streak counters that turn a sequence of single-window
classifications into one sustained, operationally-consequential state.

Entry and recovery are deliberately asymmetric, both evaluated against kappa
directly (not against the single-window state label, which collapses two
different bands into "degraded" -- see health.py's module docstring):
  - entry streak increments only when kappa <= drift_entry_threshold, and
    resets to 0 on any window that doesn't meet that -- including the "middle
    band" between the two thresholds, which is neither a breach nor a
    recovery.
  - recovery streak increments only when kappa >= recovery_threshold, with
    the same reset behavior.
  - insufficient_data windows advance neither counter: they carry no
    information about accuracy in either direction.

Once `drifted`, the exposed state is sticky -- it does not flicker back to
healthy/degraded on individual good windows, only after
recovery_consecutive_windows consecutive windows clear the (stricter)
recovery bar. This is the asymmetry from the Day 6 Phase 0 build-log entry:
catching real drift fast (small, non-sticky entry) is favored over tolerating
conservatism (slow, sticky recovery).
"""
from __future__ import annotations

from collections import deque
from typing import Literal, get_args

from finsentry.reliability.health import (
    DriftConfig,
    JudgeHealthRecord,
    JudgeHealthState,
    LabeledResult,
    compute_window_health,
)

OperatingMode = Literal["normal", "frontier_only"]
_OPERATING_MODE_VALUES = set(get_args(OperatingMode))


class DriftController:
    """One instance tracks one judge's accuracy-drift health over time."""

    def __init__(self, config: DriftConfig | None = None) -> None:
        self._config = config or DriftConfig()
        self._window: deque[LabeledResult] = deque(maxlen=self._config.window_size)
        self._entry_streak = 0
        self._recovery_streak = 0
        self._sustained_state: JudgeHealthState = "insufficient_data"
        self._ever_had_sufficient_data = False
        self._operationally_unavailable = False

    @property
    def config(self) -> DriftConfig:
        return self._config

    @property
    def entry_streak(self) -> int:
        """Read-only: the minimal hook a transition-audit observer needs to
        report full evidence without reaching into private state. Does not
        change core hysteresis logic."""
        return self._entry_streak

    @property
    def recovery_streak(self) -> int:
        return self._recovery_streak

    def mark_operationally_unavailable(self) -> None:
        """Call when the judge's own operational JudgeHealth (uptime/error
        rate, a separate signal -- see health.py's module docstring) reports
        unavailable. Accuracy drift is undefined for a judge that is not
        running at all, so this overrides whatever the kappa history says."""
        self._operationally_unavailable = True

    def mark_operationally_available(self) -> None:
        """Clears the override from mark_operationally_unavailable(). Does
        not by itself change the kappa-derived sustained state -- the next
        windowed reading does that."""
        self._operationally_unavailable = False

    def record_result(self, result: LabeledResult) -> JudgeHealthRecord:
        """Append one new labeled canary result to the rolling window and
        re-evaluate. Returns this tick's JudgeHealthRecord."""
        self._window.append(result)
        record = compute_window_health(list(self._window), self._config)
        self._apply_hysteresis(record)
        return record

    def _apply_hysteresis(self, record: JudgeHealthRecord) -> None:
        cfg = self._config

        if record.state == "insufficient_data":
            if not self._ever_had_sufficient_data:
                self._sustained_state = "insufficient_data"
            return  # neither streak advances -- no information either way

        self._ever_had_sufficient_data = True
        kappa = record.kappa
        assert kappa is not None  # committed_n >= min_n > 0 whenever state != insufficient_data

        if kappa <= cfg.drift_entry_threshold:
            self._entry_streak += 1
            self._recovery_streak = 0
        elif kappa >= cfg.recovery_threshold:
            self._recovery_streak += 1
            self._entry_streak = 0
        else:
            self._entry_streak = 0
            self._recovery_streak = 0

        if self._sustained_state == "drifted":
            if self._recovery_streak >= cfg.recovery_consecutive_windows:
                self._sustained_state = "healthy"
                self._entry_streak = 0
                self._recovery_streak = 0
            # else: stays drifted (sticky) regardless of this window's label
        elif self._entry_streak >= cfg.entry_consecutive_windows:
            self._sustained_state = "drifted"
        else:
            self._sustained_state = record.state  # mirrors this window: healthy/degraded

    @property
    def current_state(self) -> JudgeHealthState:
        if self._operationally_unavailable:
            return "unavailable"
        return self._sustained_state

    @property
    def current_mode(self) -> OperatingMode:
        """normal: the wrapped judge is admitted as-is. frontier_only: the
        wrapped judge is bypassed (admitted as unavailable) -- drifted or
        operationally unavailable both gate the same way, since in both
        cases this judge's output should not be trusted right now."""
        mode: OperatingMode = (
            "frontier_only" if self.current_state in ("drifted", "unavailable") else "normal"
        )
        assert mode in _OPERATING_MODE_VALUES
        return mode
