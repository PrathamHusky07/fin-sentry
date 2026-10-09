"""Tests for scripts/load_test.py start_stack: the run must not generate load against a
consumer group that never became ready, because the consumer starts at the latest offset and
would silently miss every event sent before it joined."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import load_test  # noqa: E402


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _patch_stack(
    monkeypatch: pytest.MonkeyPatch, states: list[dict[str, Any]], isolation: MagicMock
) -> None:
    """Everything start_stack touches outside the readiness wait is replaced. `states` is
    what group_state returns in order, then its last entry repeats."""
    clock = _Clock()
    monkeypatch.setattr(
        load_test, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    )
    monkeypatch.setattr(load_test, "spawn", lambda *a, **k: MagicMock())
    monkeypatch.setattr(load_test, "wait_for_file", lambda *a, **k: {"pid": 1})
    monkeypatch.setattr(load_test, "verify_isolation", isolation)
    calls = iter(states)
    last = states[-1]
    monkeypatch.setattr(load_test, "group_state", lambda *a, **k: next(calls, last))


def _start(tmp_path: Path) -> dict[str, Any]:
    run = load_test.Run(tmp_path)
    summary: dict[str, Any] = {}
    args = argparse.Namespace(stub_latency_ms=200.0)
    load_test.start_stack(args, run, summary, [])
    return summary


def test_a_consumer_group_that_never_stabilizes_aborts_before_any_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    isolation = MagicMock(return_value={"passed": True})
    # An unreadable or missing group parses to state None and no members.
    _patch_stack(monkeypatch, [{"state": None, "members": 0}], isolation)
    with pytest.raises(RuntimeError, match="consumer group"):
        _start(tmp_path)
    isolation.assert_not_called()  # it stopped before the isolation check, let alone load


def test_a_group_stuck_rebalancing_aborts_and_says_what_it_saw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_stack(monkeypatch, [{"state": "PreparingRebalance", "members": 1}], MagicMock())
    with pytest.raises(RuntimeError, match="PreparingRebalance"):
        _start(tmp_path)


def test_a_stable_group_with_a_member_starts_normally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    isolation = MagicMock(return_value={"passed": True})
    _patch_stack(
        monkeypatch,
        [{"state": "Empty", "members": 0}, {"state": "Stable", "members": 1}],
        isolation,
    )
    summary = _start(tmp_path)
    isolation.assert_called_once()
    assert summary["isolation_check"] == {"passed": True}


def test_a_stable_group_with_no_member_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_stack(monkeypatch, [{"state": "Stable", "members": 0}], MagicMock())
    with pytest.raises(RuntimeError, match="consumer group"):
        _start(tmp_path)
