"""
AsyncCircuitBreaker: per-endpoint async circuit breaker.

Failure taxonomy (what counts as a failure and what does not):

  Failures -- increment counter, retry within budget:
    - HTTP 500, 502, 503, 504 from downstream
    - Connection errors: connection refused, connection reset, DNS failure
      (httpx.ConnectError and subclasses)
    - httpx.TimeoutException on individual attempt

  Not failures -- do not retry, do not increment counter:
    - HTTP 400, 422 from downstream: the caller sent a bad request; retrying
      the same payload produces the same error, and the downstream is healthy.
    - HTTP 401, 403 from downstream: auth misconfiguration on our side;
      downstream is healthy; retrying achieves nothing.

  Special case -- retry within budget, do NOT increment counter:
    - HTTP 429 from downstream: downstream is alive but rate-limiting us.
      Rate limits are not health signals. If the 20-second request budget
      expires while retrying 429s, return 429 to the caller (not 504).

This taxonomy is documented in ADR 004.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"


class AsyncCircuitBreaker:
    """State-machine circuit breaker safe for concurrent async callers.

    Use one instance per logical endpoint. Inject `_now` in tests to control
    the clock without real sleep.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "",
        _now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._now = _now
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def is_open(self) -> tuple[bool, float]:
        """Return (is_open, seconds_until_close).

        Transitions OPEN to CLOSED when recovery_timeout has elapsed so the
        next caller gets a probe attempt rather than an immediate 503.
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                assert self._opened_at is not None
                elapsed = self._now() - self._opened_at
                remaining = self.recovery_timeout - elapsed
                if remaining <= 0:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._opened_at = None
                    return False, 0.0
                return True, remaining
            return False, 0.0

    async def record_failure(self) -> None:
        """Increment the failure counter; trip the breaker if threshold is met.

        Once OPEN, additional record_failure calls do not reset _opened_at.
        The recovery window starts when the breaker first opens, not on the last failure.
        """
        async with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = self._now()

    async def record_success(self) -> None:
        """Reset the failure counter on a successful probe after recovery."""
        async with self._lock:
            self._failure_count = 0

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def state(self) -> CircuitState:
        return self._state
