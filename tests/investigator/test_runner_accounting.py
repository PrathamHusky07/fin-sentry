"""The runner records what a failing investigator already spent, survives a malformed
result, and versions the scoring rules alongside the cases."""

from __future__ import annotations

import pytest

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import InvestigationState
from finsentry.investigator.evaluation import scorer
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.runner import run_case, run_suite
from finsentry.investigator.loop import Clock, InvestigationFailedError
from finsentry.investigator.policy import record_inference
from finsentry.investigator.stub import AlwaysAbstainInvestigator

CASE = all_cases()[0]


class SpendsThenRaises:
    agent_version = "spends-then-raises-0"

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> None:
        await tools.call("get_drift_report", "q1")
        await tools.call("get_trace_detail", "q2", app_trace_id="jf-01")
        await tools.call("get_trace_detail", "q3", app_trace_id="jf-02")
        raise RuntimeError("boom")


class FailsWithItsState:
    agent_version = "fails-with-state-0"

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> None:
        await tools.call("get_drift_report", "q1")
        raise InvestigationFailedError("the planner hung", record_inference(state))


class ReturnsGarbage:
    agent_version = "garbage-0"

    def __init__(self, value: object) -> None:
        self.value = value

    async def investigate(self, *_: object) -> object:
        return self.value


async def test_a_failure_keeps_the_tool_calls_already_made() -> None:
    score = await run_case(SpendsThenRaises(), CASE, lambda: 0.0)  # type: ignore[arg-type]
    assert score.actual_outcome == "no_report" and not score.passed
    assert score.tool_calls == 3
    assert "RuntimeError: boom" in score.flags


async def test_a_failure_that_carries_its_state_keeps_the_inference_calls_too() -> None:
    score = await run_case(FailsWithItsState(), CASE, lambda: 0.0)  # type: ignore[arg-type]
    assert score.inference_calls == 1 and score.tool_calls == 1


@pytest.mark.parametrize("value", [None, {"report": 1}, "not a result", object()])
async def test_a_malformed_result_is_a_case_failure(value: object) -> None:
    score = await run_case(ReturnsGarbage(value), CASE, lambda: 0.0)  # type: ignore[arg-type]
    assert score.actual_outcome == "no_report" and not score.passed
    assert score.flags[0] == "investigator_error"


async def test_a_malformed_result_does_not_abort_the_suite() -> None:
    result = await run_suite(ReturnsGarbage(None), all_cases()[:2], clock=lambda: 0.0)  # type: ignore[arg-type]
    assert [c.actual_outcome for c in result.cases] == ["no_report", "no_report"]
    assert result.summary["cases"] == 2


async def test_a_change_to_the_scoring_rules_changes_the_version_but_not_the_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = all_cases()[:2]
    before = await run_suite(AlwaysAbstainInvestigator(), cases, clock=lambda: 0.0)
    reweighted = {**scorer.DIAGNOSIS_WEIGHTS, "efficiency": 0.05, "verification": 0.20}
    monkeypatch.setattr(scorer, "DIAGNOSIS_WEIGHTS", reweighted)
    after = await run_suite(AlwaysAbstainInvestigator(), cases, clock=lambda: 0.0)

    assert before.cases_fingerprint == after.cases_fingerprint
    assert before.scoring_version != after.scoring_version
    assert before.suite_fingerprint != after.suite_fingerprint
    assert before.tool_contract_version == after.tool_contract_version


async def test_the_same_rules_and_cases_give_the_same_fingerprints() -> None:
    cases = all_cases()[:2]
    a = await run_suite(AlwaysAbstainInvestigator(), cases, clock=lambda: 0.0)
    b = await run_suite(AlwaysAbstainInvestigator(), cases, clock=lambda: 0.0)
    assert (a.suite_fingerprint, a.scoring_version) == (b.suite_fingerprint, b.scoring_version)
