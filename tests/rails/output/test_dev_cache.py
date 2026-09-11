"""Tests for the dev-mode cache stub."""
from __future__ import annotations

from finsentry.rails.output._dev_cache import _DisabledCache


def test_disabled_cache_returns_none_for_any_key() -> None:
    cache = _DisabledCache()
    assert cache.get("any-key") is None
    assert cache.get("another-key") is None


def test_disabled_cache_put_is_a_noop() -> None:
    cache = _DisabledCache()
    cache.put("key", "some response text")
    assert cache.get("key") is None
