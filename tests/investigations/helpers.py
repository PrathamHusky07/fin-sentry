"""Shared builders for the investigation session tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg

from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.planner_double import PlannerDouble
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.planning import Plan, Planner
from finsentry.investigator.service import InvestigationDeps
from finsentry.investigator.tool_contract import McpReadTools
from tests.conftest import TEST_DATABASE_URL

CASES = {c.case_id: c for c in all_cases()}


class GatedPlanner:
    """The planner double, held until released, so a test can act while a session runs. It
    counts the calls it receives."""

    name = "gated-double"
    cost_usd = 0.0

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls = 0
        self._inner = PlannerDouble()

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        self.calls += 1
        await self.release.wait()
        return await self._inner.plan(digest, round_no=round_no)


class ForbiddenPlanner:
    """A planner that fails the test if it is ever asked for a plan."""

    name = "forbidden"
    cost_usd = 0.0

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        raise AssertionError("a read must never ask the planner for a plan")


def deps_for(case_id: str, planner: Planner | None) -> InvestigationDeps:
    world = FixtureWorld(CASES[case_id].world)

    @asynccontextmanager
    async def session() -> AsyncIterator[McpReadTools]:
        yield world

    return InvestigationDeps(
        database_url=TEST_DATABASE_URL,
        planner_factory=(lambda: planner) if planner is not None else None,
        tool_session=session,
        clock=lambda: 0.0,
    )


def sql(query: str, *params: object) -> list[tuple[object, ...]]:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        cur = conn.execute(query, params)  # type: ignore[arg-type]
        return cur.fetchall() if cur.description else []


async def settle(deps: InvestigationDeps) -> None:
    await asyncio.gather(*list(deps.tasks))
