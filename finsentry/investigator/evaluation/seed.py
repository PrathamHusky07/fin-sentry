"""Store fixture investigations through the real service, store and timeline code.

    python -m finsentry.investigator.evaluation.seed --replace

Each session runs a known-answer case world through the same investigator, recorder and store a
live run uses, with the planner double in place of a model. Every row is stored with origin
'fixture' and the double's name as its planner, so the page and the API say it is a replay of a
case world and never a result on the live platform. They exist to exercise the page's states
(a diagnosis, a justified abstention, an unavailable source, a failed run, an interrupted run)
without a model call. No fixture session is a measurement of the investigator.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

from dotenv import load_dotenv

from finsentry.investigator import store
from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import InvestigationResult, InvestigationState
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.planner_double import PlannerDouble
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import (
    BoundedInvestigator,
    Clock,
    InvestigationFailedError,
    Investigator,
    _Run,
    start_investigation,
)
from finsentry.investigator.service import RecordingPlanner, run_investigation
from finsentry.investigator.timeline import EventRecorder

# Which known-answer case stands in for which page state.
COMPLETED_DIAGNOSIS = "drifted-judge-misleading"
COMPLETED_REGRESSION = "schema-rail-regression"
JUSTIFIED_ABSTENTION = "ambiguous-signal"
UNAVAILABLE_SOURCE = "unavailable-source"
FAILED_RUN = "stale-chunk"
INTERRUPTED_RUN = "injection-surge"

FIXTURE_FAULT = (
    "FixtureFault: the fixture investigator was made to raise after its opening query, to show "
    "the failed state. This is not a defect found in the investigator."
)


class _RaisesAfterOpening:
    """Runs the real loop's first query and then raises, as a defect would."""

    agent_version = "fixture-raises-0"

    def __init__(self, inner: BoundedInvestigator) -> None:
        self.inner = inner

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult:
        # The loop's own opening query, run by the loop, so its event is a real one.
        run = _Run(self.inner, state, tools, clock)
        await run._open()
        raise InvestigationFailedError(FIXTURE_FAULT, run.state)


def _case(case_id: str) -> IncidentCase:
    return next(c for c in all_cases() if c.case_id == case_id)


def _request(case: IncidentCase) -> dict[str, object]:
    return {
        "kind": case.trigger.kind,
        "reference_id": case.trigger.reference_id,
        "description": case.trigger.description,
        "endpoint": case.scope.endpoint,
        "ticker": case.scope.ticker,
        "window_minutes": case.window.minutes,
        "window": case.window.model_dump(mode="json"),
        "fixture_case": case.case_id,
    }


def _create(database_url: str, case: IncidentCase, planner: str) -> tuple[str, InvestigationState]:
    investigation_id = str(uuid.uuid4())
    incident_id = f"inc-{investigation_id[:8]}"
    store.create(
        database_url,
        investigation_id=investigation_id,
        incident_id=incident_id,
        origin="fixture",
        planner=planner,
        agent_version=f"bounded-investigator-1+{planner}",
        request=_request(case),
        request_key=f"fixture:{case.case_id}",
    )
    state = start_investigation(incident_id, case.trigger, case.window, scope=case.scope)
    return investigation_id, state


async def seed_case(database_url: str, case_id: str, *, crash: bool = False) -> str:
    """Run one case world through the real session code and return the stored session id."""
    case = _case(case_id)
    double = PlannerDouble()
    investigation_id, state = await asyncio.to_thread(_create, database_url, case, double.name)

    def investigator(planner: RecordingPlanner, recorder: EventRecorder) -> Investigator:
        real = BoundedInvestigator(planner, recorder=recorder)
        return _RaisesAfterOpening(real) if crash else real

    await run_investigation(
        database_url,
        investigation_id,
        state,
        FixtureWorld(case.world),
        double,
        clock=lambda: 0.0,
        investigator=investigator,
    )
    return investigation_id


async def seed_interrupted(database_url: str, case_id: str) -> str:
    """A session whose process stopped partway: it stored its first events and then went quiet,
    and it is ended with the text and the guarded write the store uses for a stale session."""
    case = _case(case_id)
    double = PlannerDouble()
    investigation_id, state = await asyncio.to_thread(_create, database_url, case, double.name)
    recorder = EventRecorder(
        lambda e: asyncio.to_thread(store.append_event, database_url, investigation_id, e)
    )
    adapter = ReadOnlyAdapter(FixtureWorld(case.world))
    owner = BoundedInvestigator(RecordingPlanner(double), recorder=recorder)
    await _Run(owner, state, adapter, lambda: 0.0)._open()
    await recorder.flush()
    await asyncio.to_thread(
        store.end_without_report,
        database_url,
        investigation_id,
        "interrupted",
        store.STALE_ERROR,
        None,
        None,
    )
    return investigation_id


async def seed_all(database_url: str, *, replace: bool) -> dict[str, str]:
    if replace:
        await asyncio.to_thread(store.delete_fixtures, database_url)
    return {
        "diagnosis": await seed_case(database_url, COMPLETED_DIAGNOSIS),
        "regression": await seed_case(database_url, COMPLETED_REGRESSION),
        "abstention": await seed_case(database_url, JUSTIFIED_ABSTENTION),
        "unavailable": await seed_case(database_url, UNAVAILABLE_SOURCE),
        "failed": await seed_case(database_url, FAILED_RUN, crash=True),
        "interrupted": await seed_interrupted(database_url, INTERRUPTED_RUN),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="delete fixture sessions first")
    args = parser.parse_args()
    load_dotenv()
    ids = asyncio.run(seed_all(os.environ["DATABASE_URL"], replace=args.replace))
    for label, investigation_id in ids.items():
        print(f"{label:12s} {investigation_id}")


if __name__ == "__main__":
    main()
