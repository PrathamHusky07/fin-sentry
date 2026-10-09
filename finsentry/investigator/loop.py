"""
The interface the eval harness runs, and the way an investigation starts.

Investigator is what Day 11.1 implements. Day 11.0 ships only AlwaysAbstainInvestigator
(stub.py), which exists to exercise the harness before any reasoning does. Nothing here
decides anything.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from finsentry.investigator.adapter import KNOWN_TOOL_GAPS, ReadOnlyAdapter
from finsentry.investigator.contracts import (
    AffectedScope,
    Budgets,
    DataGap,
    IncidentTrigger,
    InvestigationResult,
    InvestigationState,
    TimeWindow,
)

Clock = Callable[[], float]


class InvestigationFailedError(RuntimeError):
    """An investigation that could not finish. It carries the last good state so a runner can
    still account for the tool and inference calls already spent."""

    def __init__(self, message: str, state: InvestigationState) -> None:
        super().__init__(message)
        self.state = state


class Investigator(Protocol):
    agent_version: str

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult: ...


def start_investigation(
    incident_id: str,
    trigger: IncidentTrigger,
    window: TimeWindow,
    *,
    scope: AffectedScope | None = None,
    extra_gaps: list[DataGap] | None = None,
    budgets: Budgets | None = None,
) -> InvestigationState:
    """A fresh state with the tools' known data gaps already declared."""
    return InvestigationState(
        incident_id=incident_id,
        trigger=trigger,
        window=window,
        scope=scope or AffectedScope(),
        known_data_gaps=[*KNOWN_TOOL_GAPS, *(extra_gaps or [])],
        budgets=budgets or Budgets(),
    )
