"""
get_drift_report: the last-persisted judge-accuracy-drift evidence for the
Day 6 reliability mechanism.

No RisingWave access -- this tool reads the live canary smoke artifact and
the transition-audit log (if present) from disk, plus the live, authoritative
DriftConfig policy values. Numeric policy constants (0.43/0.54/150/30/K/M/
baseline) are never duplicated as literals here; they come from
finsentry.reliability.health.DriftConfig(), the one source of truth.

Day 6 proved this mechanism with a bounded, one-shot live canary run and
synthetic hysteresis tests -- it is not wired into a continuously running
scheduler. This tool reports whatever was last written to disk, with an
explicit as-of timestamp, and must never be read as "live monitoring."
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finsentry.reliability.health import DriftConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_LIVE_SMOKE_PATH = _REPO_ROOT / "docs/measurements/reliability/canary-live-smoke-d6p2.json"
_TRANSITIONS_PATH = _REPO_ROOT / "docs/measurements/reliability/canary_transitions.json"

_MONITORED_JUDGE_ID = "gemini-rubric"  # the only judge Day 6 monitors today


@dataclass
class DriftPolicy:
    window_size: int
    min_n: int
    healthy_baseline_kappa: float
    drift_entry_threshold: float
    recovery_threshold: float
    entry_consecutive_windows: int
    recovery_consecutive_windows: int


@dataclass
class LastHealthReading:
    state: str | None
    kappa: float | None
    window_n: int | None
    committed_n: int | None
    n_abstain: int | None
    n_unavailable: int | None
    state_as_of: str | None
    source: str


@dataclass
class TransitionRecordSummary:
    observed_at: str | None
    previous_state: str
    new_state: str
    previous_mode: str
    new_mode: str
    reason: str
    kappa: float | None


@dataclass
class GetDriftReportResult:
    judge_id: str
    policy: DriftPolicy
    last_health_reading: LastHealthReading | None
    transition_history: list[TransitionRecordSummary]
    note: str


def _policy_from_config(config: DriftConfig) -> DriftPolicy:
    return DriftPolicy(
        window_size=config.window_size,
        min_n=config.min_n,
        healthy_baseline_kappa=config.healthy_baseline_kappa,
        drift_entry_threshold=config.drift_entry_threshold,
        recovery_threshold=config.recovery_threshold,
        entry_consecutive_windows=config.entry_consecutive_windows,
        recovery_consecutive_windows=config.recovery_consecutive_windows,
    )


def _load_last_health_reading(path: Path) -> LastHealthReading | None:
    if not path.exists():
        return None
    smoke: dict[str, Any] = json.loads(path.read_text())
    health = smoke.get("health_record")
    if health is None:
        return None
    observations = smoke.get("observations", [])
    state_as_of = max((o["observed_at"] for o in observations), default=None)
    return LastHealthReading(
        state=health.get("state"),
        kappa=health.get("kappa"),
        window_n=health.get("window_n"),
        committed_n=health.get("committed_n"),
        n_abstain=health.get("n_abstain"),
        n_unavailable=health.get("n_unavailable"),
        state_as_of=state_as_of,
        source=str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else str(path),
    )


def _load_transition_history(path: Path) -> list[TransitionRecordSummary]:
    if not path.exists():
        return []
    raw: list[dict[str, Any]] = json.loads(path.read_text())
    return [
        TransitionRecordSummary(
            observed_at=t.get("observed_at"),
            previous_state=t["previous_state"],
            new_state=t["new_state"],
            previous_mode=t["previous_mode"],
            new_mode=t["new_mode"],
            reason=t["reason"],
            kappa=t.get("kappa"),
        )
        for t in raw
    ]


def _report_note(last_reading: LastHealthReading | None, transitions: list[Any]) -> str:
    if last_reading is None:
        return "no live canary health reading has been persisted yet"
    if not transitions:
        return (
            "reporting last-persisted state as of state_as_of; this is not a "
            "continuously running monitor. No transition-audit history exists "
            "yet -- the judge has not crossed any hysteresis threshold since "
            "the audit wrapper was last used"
        )
    return (
        "reporting last-persisted state as of state_as_of; this is not a "
        "continuously running monitor"
    )


async def get_drift_report() -> GetDriftReportResult:
    """Report the last-persisted judge-accuracy-drift evidence: the most
    recent canary health reading, the transition-audit history (if any),
    and the authoritative policy thresholds read live from DriftConfig.
    Answers "is the evaluator drifting, and what's the evidence?" with the
    last snapshot on disk -- not a live feed."""
    policy = _policy_from_config(DriftConfig())
    last_reading = _load_last_health_reading(_LIVE_SMOKE_PATH)
    transitions = _load_transition_history(_TRANSITIONS_PATH)

    return GetDriftReportResult(
        judge_id=_MONITORED_JUDGE_ID,
        policy=policy,
        last_health_reading=last_reading,
        transition_history=transitions,
        note=_report_note(last_reading, transitions),
    )
