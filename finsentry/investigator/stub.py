"""
The always-abstain investigator.

It runs the loop skeleton (clock, stopping policy, report, validation) and makes no
decision. It calls no tool and no model, and it always returns the abstention report. Its
only purpose is to let the harness be tested before any reasoning exists. It is not a
quality baseline for the future agent: scoring well on abstention cases is the one thing
it can do, and scoring badly on the rest is the evidence that the harness discriminates.
"""

from __future__ import annotations

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import InvestigationResult, InvestigationState
from finsentry.investigator.loop import Clock
from finsentry.investigator.policy import decide_stop, finish, with_elapsed
from finsentry.investigator.reports import abstention_report


class AlwaysAbstainInvestigator:
    agent_version = "always-abstain-0"

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult:
        started = clock()
        state = with_elapsed(state, clock() - started)
        reason = decide_stop(state, abstain=True)
        if reason is None:
            raise RuntimeError("the stopping policy did not stop an abstaining run")
        state = finish(state, reason)
        report = abstention_report(state)
        validation = validate_report(report, state)
        if not validation.valid:
            raise RuntimeError(f"the abstention report is invalid: {validation.problems}")
        return InvestigationResult(report=report, state=state)
