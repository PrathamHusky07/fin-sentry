"""
Judge accuracy-drift health: pure, deterministic classification of a judge's
recent agreement with ground truth.

This is a different axis from `finsentry.frontier.types.JudgeHealth` /
`JudgeHealthStatus`, which is operational (uptime, error rate, computed by
each adapter's own `health_check()` liveness ping). That signal answers "is
the judge responding." This module answers "when the judge responds, is it
still right" -- an operationally perfectly healthy judge can still have
drifted in accuracy (a model update, a prompt-sensitive distribution shift),
which `JudgeHealth.error_rate_1h` cannot see at all. The two are not unified
into one type because their fields don't overlap (error_rate_1h/
last_success_ts have no meaning here; kappa/window/threshold have no meaning
there) -- see docs/build-log.md's Day 6 Phase 0 entry for the full reasoning.

compute_window_health() only ever classifies a single window into
{insufficient_data, healthy, degraded}. "drifted" and "unavailable" are
states the stateful hysteresis controller (finsentry/reliability/controller.py)
layers on top of a sequence of these -- a single window's kappa is never
itself "drifted" (that requires sustained evidence) and never "unavailable"
(that is an operational fact this module has no visibility into).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from finsentry.calibration.metrics import cohens_kappa, confusion_matrix
from finsentry.frontier.types import JudgeDecision

JudgeHealthState = Literal["healthy", "degraded", "drifted", "insufficient_data", "unavailable"]
_JUDGE_HEALTH_STATE_VALUES = set(get_args(JudgeHealthState))

# Derived from the frozen 500-row M4 dataset (docs/build-log.md, Day 6 Phase 0
# entry) -- not textbook constants. Recomputing them requires re-running that
# analysis against a frozen artifact; they are not expected to change on their
# own, so they are module constants rather than something read from a file.
DEFAULT_WINDOW_SIZE = 150
DEFAULT_MIN_N = 30
DEFAULT_HEALTHY_BASELINE_KAPPA = 0.6050
DEFAULT_DRIFT_ENTRY_THRESHOLD = 0.43
DEFAULT_RECOVERY_THRESHOLD = 0.54
DEFAULT_ENTRY_CONSECUTIVE_WINDOWS = 3
DEFAULT_RECOVERY_CONSECUTIVE_WINDOWS = 5


@dataclass
class LabeledResult:
    """One judge decision on one benchmark-labeled (canary) item.

    decision is the adapter's own thresholded categorical call -- the same
    JudgeDecision JudgeResult carries, not a re-derivation from the raw
    faithfulness_score. "abstain" and "unavailable" are valid values here;
    compute_window_health decides how to treat them, not the caller.
    """

    decision: JudgeDecision
    gold_is_hallucination: bool
    # ISO-8601 string, supplied by the caller -- never datetime.now() inside this
    # module (compute_window_health stays pure/deterministic, see module docstring).
    observed_at: str


@dataclass(frozen=True)
class DriftConfig:
    """Policy constants for windowed health classification and hysteresis.

    Defaults are the Day 6 Phase 0 derivation (see module docstring above);
    override in tests to use small windows/streaks for fast synthetic
    scenarios without changing production behavior.
    """

    window_size: int = DEFAULT_WINDOW_SIZE
    min_n: int = DEFAULT_MIN_N
    healthy_baseline_kappa: float = DEFAULT_HEALTHY_BASELINE_KAPPA
    drift_entry_threshold: float = DEFAULT_DRIFT_ENTRY_THRESHOLD
    recovery_threshold: float = DEFAULT_RECOVERY_THRESHOLD
    entry_consecutive_windows: int = DEFAULT_ENTRY_CONSECUTIVE_WINDOWS
    recovery_consecutive_windows: int = DEFAULT_RECOVERY_CONSECUTIVE_WINDOWS

    def __post_init__(self) -> None:
        if self.min_n > self.window_size:
            raise ValueError(
                f"DriftConfig.min_n={self.min_n} must be <= window_size={self.window_size}"
            )
        if self.recovery_consecutive_windows < self.entry_consecutive_windows:
            raise ValueError(
                "DriftConfig.recovery_consecutive_windows must be >= "
                f"entry_consecutive_windows (got {self.recovery_consecutive_windows} < "
                f"{self.entry_consecutive_windows}) -- recovery must not be easier than entry"
            )
        if self.min_n < 1 or self.window_size < 1:
            raise ValueError("DriftConfig.min_n and window_size must be >= 1")
        if self.entry_consecutive_windows < 1 or self.recovery_consecutive_windows < 1:
            raise ValueError(
                "DriftConfig.entry_consecutive_windows and recovery_consecutive_windows "
                "must be >= 1"
            )
        # Kappa's theoretical range is [-1, 1], but a threshold below 0 is
        # nonsensical for this policy: this mechanism exists to catch a judge
        # performing worse than chance-corrected agreement, and a negative
        # bar would mean "healthy" tolerates worse-than-chance agreement.
        for field_name, value in (
            ("drift_entry_threshold", self.drift_entry_threshold),
            ("recovery_threshold", self.recovery_threshold),
            ("healthy_baseline_kappa", self.healthy_baseline_kappa),
        ):
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"DriftConfig.{field_name}={value!r} must be in [0.0, 1.0]")
        # healthy_baseline_kappa is a live invariant, not a decorative field:
        # recovery can never be set to reclaim a judge at a bar stricter than
        # its own established healthy baseline.
        entry, recovery, baseline = (
            self.drift_entry_threshold,
            self.recovery_threshold,
            self.healthy_baseline_kappa,
        )
        if not (entry < recovery <= baseline):
            raise ValueError(
                "DriftConfig requires drift_entry_threshold < recovery_threshold <= "
                f"healthy_baseline_kappa (got {self.drift_entry_threshold} < "
                f"{self.recovery_threshold} <= {self.healthy_baseline_kappa})"
            )


@dataclass
class JudgeHealthRecord:
    """The classification of one window, plus the evidence behind it."""

    state: JudgeHealthState
    kappa: float | None
    window_n: int
    committed_n: int
    n_abstain: int
    n_unavailable: int
    config: DriftConfig
    # The max observed_at among this window's results (None for an empty
    # window), and the entry/recovery thresholds this record was classified
    # against -- both duplicated from config onto the record so a caller
    # holding one record has the full evidence without re-inspecting config.
    latest_observed_at: str | None
    entry_threshold: float
    recovery_threshold: float

    def __post_init__(self) -> None:
        if self.state not in _JUDGE_HEALTH_STATE_VALUES:
            raise ValueError(
                f"JudgeHealthRecord.state={self.state!r} not in {_JUDGE_HEALTH_STATE_VALUES}"
            )


def compute_window_health(
    labeled_results: list[LabeledResult], config: DriftConfig | None = None
) -> JudgeHealthRecord:
    """Classify one window of labeled canary results. Pure, no I/O.

    "supported"/"refuted" decisions are mapped to predicted
    faithful/hallucination and compared against gold via
    finsentry.calibration.metrics.cohens_kappa (reused, not reimplemented).
    "abstain" and "unavailable" decisions are excluded from the kappa
    computation (see module docstring) but counted in the returned evidence.

    committed_n < config.min_n -> state="insufficient_data" regardless of the
    (still-computed, if any) kappa value -- a kappa on too few committed
    decisions is not trustworthy enough to classify on, but is reported as
    evidence rather than withheld.
    """
    cfg = config or DriftConfig()

    n_abstain = sum(1 for r in labeled_results if r.decision == "abstain")
    n_unavailable = sum(1 for r in labeled_results if r.decision == "unavailable")
    committed = [r for r in labeled_results if r.decision in ("supported", "refuted")]
    committed_n = len(committed)

    kappa: float | None = None
    if committed_n > 0:
        gold = [r.gold_is_hallucination for r in committed]
        predicted = [r.decision == "refuted" for r in committed]
        kappa = cohens_kappa(confusion_matrix(gold, predicted))

    if committed_n < cfg.min_n:
        state: JudgeHealthState = "insufficient_data"
    elif kappa is not None and kappa >= cfg.recovery_threshold:
        state = "healthy"
    else:
        state = "degraded"

    return JudgeHealthRecord(
        state=state,
        kappa=kappa,
        window_n=len(labeled_results),
        committed_n=committed_n,
        n_abstain=n_abstain,
        n_unavailable=n_unavailable,
        config=cfg,
        latest_observed_at=_latest_observed_at(labeled_results),
        entry_threshold=cfg.drift_entry_threshold,
        recovery_threshold=cfg.recovery_threshold,
    )


def _latest_observed_at(labeled_results: list[LabeledResult]) -> str | None:
    """Max observed_at among the window's results, or None if empty. Parses
    to datetime for correct chronological comparison (not relying on
    ISO-string lexicographic ordering), but returns the original string."""
    if not labeled_results:
        return None
    return max(labeled_results, key=lambda r: datetime.fromisoformat(r.observed_at)).observed_at
