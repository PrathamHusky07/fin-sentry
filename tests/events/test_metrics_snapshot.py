from __future__ import annotations

import datetime

from finsentry.events.metrics_snapshot import is_stale


def test_is_stale_none_anchor_is_conservative_true() -> None:
    """No window_end at all (e.g. zero frontier activity in the lookback) is
    stale by construction -- the conservative default when the data can't
    distinguish "nothing happened" from "the pipeline is dead."""
    now = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=datetime.UTC)
    assert is_stale(None, now=now) is True


def test_is_stale_within_two_bucket_widths_is_fresh() -> None:
    now = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=datetime.UTC)
    window_end = now - datetime.timedelta(minutes=1, seconds=59)
    assert is_stale(window_end, now=now) is False


def test_is_stale_past_two_bucket_widths_is_stale() -> None:
    now = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=datetime.UTC)
    window_end = now - datetime.timedelta(minutes=2, seconds=1)
    assert is_stale(window_end, now=now) is True
