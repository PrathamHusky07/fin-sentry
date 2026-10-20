"""The timeline records what the loop did, from values it already holds, and changes nothing
about the run. A recorder that fails or is absent leaves the result exactly as it was."""

from __future__ import annotations

import asyncio

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import InvestigationResult
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.planner_double import PlannerDouble
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import BoundedInvestigator, start_investigation
from finsentry.investigator.timeline import (
    Assessed,
    EventRecorder,
    QueryRun,
    Stopped,
    TimelineEntry,
    describe_records,
)

CASES = {c.case_id: c for c in all_cases()}


async def run(
    case: IncidentCase, recorder: EventRecorder | None
) -> tuple[InvestigationResult, EventRecorder | None]:
    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    result = await BoundedInvestigator(PlannerDouble(), recorder=recorder).investigate(
        state, ReadOnlyAdapter(FixtureWorld(case.world)), lambda: 0.0
    )
    return result, recorder


async def test_a_diagnosis_records_queries_a_plan_an_assessment_and_why_it_stopped() -> None:
    result, recorder = await run(CASES["stale-chunk"], EventRecorder())
    assert recorder is not None
    kinds = [e.event.kind for e in recorder.entries]
    assert kinds[0] == "query" and kinds[1] == "plan" and kinds[-1] == "stopped"
    assert [e.seq for e in recorder.entries] == list(range(1, len(kinds) + 1))
    ran = {q.query_id for q in result.state.executed_queries}
    queries = [e.event for e in recorder.entries if isinstance(e.event, QueryRun)]
    assert {q.query_id for q in queries} == ran
    stop = recorder.entries[-1].event
    assert isinstance(stop, Stopped)
    assert stop.stopping_reason == result.report.stopping_reason and stop.why


async def test_each_prediction_names_only_the_queries_that_judged_it() -> None:
    result, recorder = await run(CASES["stale-chunk"], EventRecorder())
    assert recorder is not None
    assessed = [e.event for e in recorder.entries if isinstance(e.event, Assessed)]
    assert assessed and assessed[-1].decision == "diagnose"
    ran = {q.query_id for q in result.state.executed_queries}
    seen = 0
    for h in assessed[-1].hypotheses:
        for p in h.predictions:
            assert set(p.query_ids) <= ran
            if p.state != "unknown":
                assert p.query_ids, "a judged prediction names the queries behind its verdict"
            seen += 1
    assert seen > 0


async def test_an_abstention_records_why_it_stopped() -> None:
    result, recorder = await run(CASES["unavailable-source"], EventRecorder())
    assert recorder is not None
    stop = recorder.entries[-1].event
    assert isinstance(stop, Stopped) and stop.outcome == "abstention"
    assert stop.stopping_reason == "critical_evidence_unavailable"
    queries = [e.event for e in recorder.entries if isinstance(e.event, QueryRun)]
    assert queries and all(q.status == "unavailable" for q in queries)
    assert result.report.outcome == "abstention"


async def test_a_run_with_a_recorder_equals_a_run_without_one() -> None:
    with_rec, _ = await run(CASES["stale-chunk"], EventRecorder())
    without, _ = await run(CASES["stale-chunk"], None)
    assert with_rec.report == without.report and with_rec.state == without.state


async def test_a_sink_that_fails_does_not_stop_the_run() -> None:
    async def broken(entry: TimelineEntry) -> None:
        raise OSError("the store is down")

    result, recorder = await run(CASES["stale-chunk"], EventRecorder(broken))
    assert recorder is not None
    await recorder.flush()
    assert result.report.outcome == "diagnosis" and len(recorder.entries) > 3


async def test_the_sink_receives_every_event_in_order() -> None:
    got: list[int] = []

    async def sink(entry: TimelineEntry) -> None:
        await asyncio.sleep(0)
        got.append(entry.seq)

    _, recorder = await run(CASES["stale-chunk"], EventRecorder(sink))
    assert recorder is not None
    await recorder.flush()
    assert sorted(got) == [e.seq for e in recorder.entries]


def test_a_listing_is_described_record_by_record() -> None:
    from finsentry.investigator.adapter import ToolResult

    traces = [fx.failing_trace("t-1", "guardrail_blocked", block_rail="faithfulness")]
    result = ToolResult(
        "q1",
        "get_failing_traces",
        {},
        "ok",
        [],
        fx.failing_traces_result(traces),
        None,
        0.0,
    )
    facts = describe_records(result)
    assert facts["trace:t-1"]["block_rail"] == "faithfulness"
    assert facts["trace:t-1"]["classification"] == "guardrail_blocked"
