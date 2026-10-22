"""
The password gate in front of Red Team runs.

A run fires attack scenarios through the live defenses, writes execution rows and can
reach a model that bills the project credit, so reading the console must never be enough
to start one. The password lives only in the server environment (RED_TEAM_RUN_PASSWORD).
The gate fails closed: with no password configured every run is refused. Failed attempts
are counted across all callers, because behind the same-origin proxy every browser reaches
the gateway from one address, and after MAX_FAILURES inside WINDOW_SECONDS every attempt
is refused, a correct one included, until the oldest failure ages out. The count lives in
this process, so each gateway process keeps its own.

Nothing here logs, returns or stores the password or any attempt's value.
"""

from __future__ import annotations

import hmac
import logging
import math
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

PASSWORD_ENV = "RED_TEAM_RUN_PASSWORD"
HEADER = "X-Run-Password"
MAX_FAILURES = 5
WINDOW_SECONDS = 600.0


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    status: int
    error: str
    retry_after: int | None = None


_ALLOWED = GateDecision(True, 200, "")


def runs_enabled() -> bool:
    """True when a run password is configured. The password itself never leaves this module."""
    return bool(os.environ.get(PASSWORD_ENV, ""))


class RunGate:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: deque[float] = deque()

    def reset(self) -> None:
        self._failures.clear()

    def check(self, supplied: str | None) -> GateDecision:
        configured = os.environ.get(PASSWORD_ENV, "")
        if not configured:
            return GateDecision(False, 503, "Runs are disabled: no run password is configured.")
        now = self._clock()
        while self._failures and now - self._failures[0] >= WINDOW_SECONDS:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            wait = math.ceil(self._failures[0] + WINDOW_SECONDS - now)
            return GateDecision(
                False, 429, "Too many incorrect attempts. Runs are locked for now.", max(wait, 1)
            )
        if supplied and hmac.compare_digest(supplied.encode(), configured.encode()):
            self._failures.clear()
            return _ALLOWED
        self._failures.append(now)
        log.warning(
            "red team run refused: password %s (%d recent failures)",
            "missing" if not supplied else "incorrect",
            len(self._failures),
        )
        return GateDecision(False, 401, "The run password is missing or incorrect.")


# One gate per gateway process, shared by every route that can start a run.
run_gate = RunGate()
