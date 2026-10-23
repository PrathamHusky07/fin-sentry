"""
The archived-evidence mode of the web app reads the drift policy from a copy of its numbers
(web/lib/archive/drift-policy.json), because it cannot import Python. This test fails when the
copy stops matching DriftConfig, so the archived calibration panel can never show thresholds
the platform no longer uses.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from finsentry.reliability.health import DriftConfig

_COPY = Path(__file__).resolve().parents[2] / "web" / "lib" / "archive" / "drift-policy.json"


def test_web_drift_policy_copy_matches_drift_config() -> None:
    copy = json.loads(_COPY.read_text())
    live = {f.name: getattr(DriftConfig(), f.name) for f in dataclasses.fields(DriftConfig)}
    assert copy == live
