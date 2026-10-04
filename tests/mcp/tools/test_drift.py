from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finsentry.mcp.tools import drift
from finsentry.reliability.health import DriftConfig


async def test_get_drift_report_reads_real_artifacts(tmp_path: Path, monkeypatch: Any) -> None:
    smoke_path = tmp_path / "canary-live-smoke-d6p2.json"
    smoke_path.write_text(
        json.dumps(
            {
                "health_record": {
                    "state": "degraded",
                    "kappa": 0.5161290322580646,
                    "window_n": 30,
                    "committed_n": 30,
                    "n_abstain": 0,
                    "n_unavailable": 0,
                },
                "observations": [
                    {"id": "a", "observed_at": "2026-10-04T17:00:00+00:00"},
                    {"id": "b", "observed_at": "2026-10-04T17:11:56.703109+00:00"},
                ],
            }
        )
    )
    transitions_path = tmp_path / "canary_transitions.json"
    transitions_path.write_text(
        json.dumps(
            [
                {
                    "observed_at": "2026-10-04T17:05:00+00:00",
                    "previous_state": "healthy",
                    "new_state": "degraded",
                    "previous_mode": "normal",
                    "new_mode": "normal",
                    "reason": "window_classification_change",
                    "kappa": 0.5,
                }
            ]
        )
    )
    monkeypatch.setattr(drift, "_LIVE_SMOKE_PATH", smoke_path)
    monkeypatch.setattr(drift, "_TRANSITIONS_PATH", transitions_path)

    result = await drift.get_drift_report()

    assert result.judge_id == "gemini-rubric"
    assert result.last_health_reading is not None
    assert result.last_health_reading.state == "degraded"
    assert result.last_health_reading.kappa == 0.5161290322580646
    assert result.last_health_reading.state_as_of == "2026-10-04T17:11:56.703109+00:00"
    assert len(result.transition_history) == 1
    assert result.transition_history[0].reason == "window_classification_change"

    # Policy must come from the live, authoritative DriftConfig, not a
    # literal duplicated in the tool.
    live_config = DriftConfig()
    assert result.policy.window_size == live_config.window_size
    assert result.policy.drift_entry_threshold == live_config.drift_entry_threshold
    assert result.policy.recovery_threshold == live_config.recovery_threshold
    assert result.policy.healthy_baseline_kappa == live_config.healthy_baseline_kappa


async def test_get_drift_report_handles_missing_artifacts_gracefully(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(drift, "_LIVE_SMOKE_PATH", tmp_path / "does-not-exist.json")
    monkeypatch.setattr(drift, "_TRANSITIONS_PATH", tmp_path / "also-missing.json")

    result = await drift.get_drift_report()

    assert result.last_health_reading is None
    assert result.transition_history == []
    assert "no live canary health reading" in result.note
