"""Dev-mode Gemini response cache. Inactive in this session; wired in Day 4.

Rationale: repeated smoke tests during development make identical Gemini calls.
A tiny disk cache keyed by (mode, model, prompt) hash returns cached responses
for identical prompts. Zero API cost for repeated dev runs. Never enabled in
production paths.
"""
from __future__ import annotations

from typing import Protocol


class ResponseCache(Protocol):
    def get(self, cache_key: str) -> str | None: ...
    def put(self, cache_key: str, response_text: str) -> None: ...


class _DisabledCache:
    """Default: no caching. Day 4 will replace with a real dev-mode implementation."""

    def get(self, cache_key: str) -> str | None:
        return None

    def put(self, cache_key: str, response_text: str) -> None:
        pass
