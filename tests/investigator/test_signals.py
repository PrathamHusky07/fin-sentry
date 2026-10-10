"""The signal evaluators: what each reads, what it cites, and when it says it cannot tell."""

from __future__ import annotations

import pytest

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import EvidenceRef, ToolName
from finsentry.investigator.signals import evaluate
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.redteam.records import ExecutionList


def result(
    tool: ToolName, payload: object, *, status: str = "ok", unverified: bool = False
) -> ToolResult:
    return ToolResult("q1", tool, {}, status, [], payload, None, 0.0, unverified)  # type: ignore[arg-type]


def detail(
    trace_id: str,
    *,
    flash: float,
    frontier: float,
    chunks: list[str],
    flagged: list[str] | None = None,
):  # type: ignore[no-untyped-def]
    return fx.trace_detail(
        trace_id,
        chunks=chunks,
        flash_faithfulness=flash,
        frontier_faithfulness=frontier,
        contradicting_chunks=flagged,
    )


def details(*items: object) -> list[ToolResult]:
    return [result("get_trace_detail", d) for d in items]


def test_a_cluster_of_judge_failures_is_present_and_cites_the_traces() -> None:
    traces = [fx.failing_trace(f"jf-{i}", "judge_pipeline_failure") for i in range(4)]
    obs = evaluate(
        "judge_failures", None, [result("get_failing_traces", fx.failing_traces_result(traces))]
    )
    assert obs.observed is True
    assert EvidenceRef(kind="trace", record_id="jf-0") in obs.support


def test_two_judge_failures_are_below_a_cluster_and_the_signal_is_absent() -> None:
    traces = [fx.failing_trace(f"jf-{i}", "judge_pipeline_failure") for i in range(2)]
    obs = evaluate(
        "judge_failures", None, [result("get_failing_traces", fx.failing_traces_result(traces))]
    )
    assert obs.observed is False


def test_a_signal_with_no_result_that_bears_on_it_cannot_be_told() -> None:
    assert evaluate("judge_drift", None, []).observed is None
    assert evaluate("block_cluster", None, []).observed is None


@pytest.mark.parametrize(
    "state, expected", [("drifted", True), ("healthy", False), ("degraded", None)]
)
def test_drift_reads_the_last_reading_and_cites_it(state: str, expected: bool | None) -> None:
    obs = evaluate("judge_drift", None, [result("get_drift_report", fx.drift_report(state=state))])
    assert obs.observed is expected
    ref = EvidenceRef(kind="drift_report", record_id="gemini-rubric")
    assert (ref in obs.support, ref in obs.against) == (expected is True, expected is False)


def _flagged(n: int, *, agree_with_chunk: int = 0) -> list[ToolResult]:
    chunks = ["C-1", "C-2"]
    items = [
        detail(f"d{i}", flash=0.9, frontier=0.1, chunks=chunks, flagged=["C-1"]) for i in range(n)
    ]
    items += [
        detail(f"a{i}", flash=0.9, frontier=0.9, chunks=chunks) for i in range(agree_with_chunk)
    ]
    return details(*items)


def test_a_chunk_flagged_on_most_disagreeing_traces_and_no_agreeing_one_is_contradicted() -> None:
    obs = evaluate("chunk_contradicted", None, _flagged(3))
    assert obs.observed is True and obs.subject == "C-1"


def test_an_agreeing_trace_that_retrieved_the_chunk_refutes_it_and_is_cited() -> None:
    obs = evaluate("chunk_contradicted", None, _flagged(3, agree_with_chunk=1))
    assert obs.observed is False
    assert EvidenceRef(kind="trace", record_id="a0") in obs.against


def test_a_chunk_flagged_on_only_some_disagreeing_traces_cannot_be_told() -> None:
    items = [
        detail("d0", flash=0.9, frontier=0.1, chunks=["C-1"], flagged=["C-1"]),
        detail("d1", flash=0.9, frontier=0.1, chunks=["C-9"], flagged=[]),
    ]
    assert evaluate("chunk_contradicted", None, details(*items)).observed is None


def test_a_single_disagreeing_trace_is_too_few_to_judge() -> None:
    assert evaluate("chunk_contradicted", None, _flagged(1)).observed is None


def _execution(execution_id: str, scenario: str, outcome: str, minutes_ago: float):  # type: ignore[no-untyped-def]
    return fx.execution(
        execution_id,
        scenario,
        "output_schema",
        outcome=outcome,  # type: ignore[arg-type]
        expected_caught_by="schema-enforcement",
        minutes_ago=minutes_ago,
    )


def test_a_miss_of_an_expected_catch_is_a_regression_and_cites_the_earlier_catch() -> None:
    listing = ExecutionList(
        executions=[
            _execution("new", "OUT-001", "missed", 5),
            _execution("old", "OUT-001", "caught", 500),
        ],
        next_offset=None,
    )
    obs = evaluate("rail_regression", None, [result("list_red_team_executions", listing)])
    assert obs.observed is True
    assert {r.record_id for r in obs.support} == {"new", "old"}


def test_a_scenario_subject_limits_the_signal_to_that_scenarios_executions() -> None:
    missed = result(
        "get_red_team_execution",
        RedTeamExecutionResult(found=True, execution=_execution("new", "OUT-001", "missed", 5)),
    )
    assert evaluate("rail_regression", "OUT-001", [missed]).observed is True
    assert evaluate("rail_regression", "OUT-002", [missed]).observed is None
    assert evaluate("rail_working", "OUT-002", [missed]).observed is None


def test_blocks_must_reach_a_cluster_on_one_rail() -> None:
    same = [
        fx.failing_trace(f"b{i}", "guardrail_blocked", block_rail="faithfulness") for i in range(6)
    ]
    mixed = [
        fx.failing_trace(f"m{i}", "guardrail_blocked", block_rail=f"rail-{i}") for i in range(6)
    ]
    few = same[:2]
    assert (
        evaluate(
            "block_cluster", None, [result("get_failing_traces", fx.failing_traces_result(same))]
        ).observed
        is True
    )
    assert (
        evaluate(
            "block_cluster", None, [result("get_failing_traces", fx.failing_traces_result(mixed))]
        ).observed
        is None
    )
    assert (
        evaluate(
            "block_cluster", None, [result("get_failing_traces", fx.failing_traces_result(few))]
        ).observed
        is False
    )


def test_an_empty_injection_search_is_absent_only_when_it_is_known_not_to_be_a_failure() -> None:
    empty = fx.injections_result([])
    verified = evaluate(
        "injection_surge", None, [result("search_prompt_injections", empty, status="empty")]
    )
    unverified = evaluate(
        "injection_surge",
        None,
        [result("search_prompt_injections", empty, status="empty", unverified=True)],
    )
    assert verified.observed is False
    assert unverified.observed is None
