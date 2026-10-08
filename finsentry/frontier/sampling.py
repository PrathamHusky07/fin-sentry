"""
Deterministic hash-based sampling for the frontier tier, with a lag-driven rate.

Hashing app_trace_id (rather than a random draw) means the same event always
produces the same sampling decision at a given rate -- replaying a
RagResponseEvent through the frontier consumer again (e.g. after a crash and
re-delivery) does not flip whether it gets evaluated, and an operator can check
"would this trace have sampled?" without needing to have observed it live.

The rate is 1 in `denominator`. The normal rate is 1 in 10 and the reduced rate
is 1 in 100. Because a hash divisible by 100 is also divisible by 10, the reduced
sample is a strict subset of the normal sample: lowering the rate never samples a
trace the normal rate would have skipped.

AdaptiveSamplingController lowers the rate while the frontier consumer group's
Kafka lag stays high and restores it once the lag stays low. Entry is fast and
recovery is slow and sticky, the same asymmetry as DriftController
(finsentry/reliability/controller.py).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

NORMAL_DENOMINATOR = 10
REDUCED_DENOMINATOR = 100

# The spec's backlog threshold is one thousand pending events. Recovery sits at a
# fifth of that, so a backlog hovering near the entry line cannot flap the rate.
DEFAULT_ENTRY_LAG = 1000
DEFAULT_RECOVERY_LAG = 200
DEFAULT_ENTRY_READINGS = 3
DEFAULT_RECOVERY_READINGS = 5


def should_sample_for_frontier(app_trace_id: str, denominator: int = NORMAL_DENOMINATOR) -> bool:
    digest = hashlib.sha256(app_trace_id.encode()).hexdigest()
    return int(digest, 16) % denominator == 0


def sampling_key(app_trace_id: str) -> str:
    """The value hashed to produce the sampling decision, carried on the
    verdict event for audit (frontier_sampling_decision_key)."""
    return app_trace_id


@dataclass(frozen=True)
class RateChange:
    from_denominator: int
    to_denominator: int
    reason: str
    lag: int


class AdaptiveSamplingController:
    """Owns the effective frontier sampling rate for one consumer process.

    Feed it one lag reading per poll with observe(). A reading of None means the
    lag monitor could not be read. That carries no information, so it holds the
    current rate and advances neither streak."""

    def __init__(
        self,
        entry_lag: int = DEFAULT_ENTRY_LAG,
        recovery_lag: int = DEFAULT_RECOVERY_LAG,
        entry_readings: int = DEFAULT_ENTRY_READINGS,
        recovery_readings: int = DEFAULT_RECOVERY_READINGS,
    ) -> None:
        if recovery_lag >= entry_lag:
            raise ValueError("recovery_lag must be below entry_lag")
        self._entry_lag = entry_lag
        self._recovery_lag = recovery_lag
        self._entry_readings = entry_readings
        self._recovery_readings = recovery_readings
        self._denominator = NORMAL_DENOMINATOR
        self._entry_streak = 0
        self._recovery_streak = 0

    @property
    def denominator(self) -> int:
        return self._denominator

    def should_sample(self, app_trace_id: str) -> bool:
        return should_sample_for_frontier(app_trace_id, self._denominator)

    def observe(self, lag: int | None) -> RateChange | None:
        """Record one lag reading. Returns the rate change it caused, if any."""
        if lag is None:
            return None
        if lag >= self._entry_lag:
            self._entry_streak += 1
            self._recovery_streak = 0
        elif lag <= self._recovery_lag:
            self._recovery_streak += 1
            self._entry_streak = 0
        else:
            self._entry_streak = 0
            self._recovery_streak = 0

        if self._denominator == NORMAL_DENOMINATOR:
            if self._entry_streak >= self._entry_readings:
                return self._change(
                    REDUCED_DENOMINATOR,
                    f"lag at or above {self._entry_lag} for {self._entry_streak} readings",
                    lag,
                )
        elif self._recovery_streak >= self._recovery_readings:
            return self._change(
                NORMAL_DENOMINATOR,
                f"lag at or below {self._recovery_lag} for {self._recovery_streak} readings",
                lag,
            )
        return None

    def _change(self, to_denominator: int, reason: str, lag: int) -> RateChange:
        change = RateChange(self._denominator, to_denominator, reason, lag)
        log.warning(
            "frontier sampling rate 1/%d -> 1/%d: %s (lag=%d)",
            change.from_denominator,
            change.to_denominator,
            reason,
            lag,
        )
        self._denominator = to_denominator
        self._entry_streak = 0
        self._recovery_streak = 0
        return change
