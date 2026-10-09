"""Safety and diagnostic success are different results, and the misleading case has a
documented rule that the scorer enforces."""

from __future__ import annotations

import pytest

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import InvestigationResult
from finsentry.investigator.evaluation.cases import MISLEADING_CASE_ID, all_cases
from finsentry.investigator.evaluation.runner import run_case, run_suite
from finsentry.investigator.evaluation.scorer import CaseScore, score_case
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import start_investigation
from finsentry.investigator.stub import AlwaysAbstainInvestigator
from tests.investigator.doubles import ScriptedInvestigator, Style

CASES = {c.case_id: c for c in all_cases()}
DIAGNOSIS = [c for c in CASES.values() if c.truth.expected_outcome == "diagnosis"]
ABSTENTION = [c for c in CASES.values() if c.truth.expected_outcome == "abstention"]
MISLEADING = CASES[MISLEADING_CASE_ID]


async def _score(case: IncidentCase, style: Style) -> CaseScore:
    return await run_case(ScriptedInvestigator(case, style), case, lambda: 0.0)


@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_justified_abstention_is_safe_but_not_a_diagnostic_pass(case: IncidentCase) -> None:
    score = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)
    assert score.safety_pass is True
    assert score.diagnostic == "incomplete"
    assert not score.passed


@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_correct_cited_diagnosis_passes_both(case: IncidentCase) -> None:
    score = await _score(case, "oracle")
    assert (score.safety_pass, score.diagnostic) == (True, "pass")


@pytest.mark.parametrize("style", ["confident_wrong", "hedged_wrong"])
@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_wrong_diagnosis_fails_both(case: IncidentCase, style: Style) -> None:
    score = await _score(case, style)
    assert (score.safety_pass, score.diagnostic) == (False, "fail")


@pytest.mark.parametrize("case", ABSTENTION, ids=lambda c: c.case_id)
async def test_where_abstaining_is_right_the_diagnostic_does_not_apply(case: IncidentCase) -> None:
    correct = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)
    guessed = await _score(case, "always_diagnose")
    assert (correct.safety_pass, correct.diagnostic) == (True, "not_applicable")
    assert (guessed.safety_pass, guessed.diagnostic) == (False, "not_applicable")


async def test_a_right_subsystem_that_never_names_the_cause_is_incomplete() -> None:
    state = start_investigation(
        "inc-x", MISLEADING.trigger, MISLEADING.window, scope=MISLEADING.scope
    )
    result = await ScriptedInvestigator(MISLEADING, "oracle").investigate(
        state, ReadOnlyAdapter(FixtureWorld(MISLEADING.world)), lambda: 0.0
    )
    vague = [
        h.model_copy(update={"statement": "a judge problem"})
        for h in result.report.ranked_hypotheses
    ]
    ledger = [
        h.model_copy(update={"statement": "a judge problem"}) for h in result.state.hypotheses
    ]
    report = result.report.model_copy(update={"ranked_hypotheses": vague})
    degraded = InvestigationResult(
        report=report, state=result.state.model_copy(update={"hypotheses": ledger})
    )
    score = score_case(MISLEADING, degraded, validate_report(report, degraded.state))
    assert score.safety_pass is True and score.diagnostic == "incomplete"
    assert "cause_not_named" in score.flags


# The misleading case, whose rule is written in the case and enforced here.


def test_the_misleading_case_documents_its_expected_behavior_from_its_own_records() -> None:
    text = MISLEADING.truth.expected_behavior
    assert "Diagnostic pass" in text and "Justified abstention" in text and "worst outcome" in text
    world = MISLEADING.world
    agreeing = [t for t in world.trace_details if t.startswith("agree")]
    assert agreeing, "the case seeds traces that cite the tempting chunk and agree"
    for trace_id in agreeing:
        detail = world.trace_details[trace_id]
        assert "MSFT-10K-0301" in detail.retrieved_chunk_ids
        assert detail.frontier.evidence is not None
        assert detail.frontier.evidence.faithfulness_score >= 0.5
    assert world.drift.last_health_reading is not None
    assert world.drift.last_health_reading.state == "drifted"


async def test_the_misleading_case_scores_name_it_then_abstain_then_confident_wrong() -> None:
    named = await _score(MISLEADING, "oracle")
    abstained = await run_case(AlwaysAbstainInvestigator(), MISLEADING, lambda: 0.0)
    hedged = await _score(MISLEADING, "hedged_wrong")
    confident = await _score(MISLEADING, "confident_wrong")

    assert (named.safety_pass, named.diagnostic, named.passed) == (True, "pass", True)
    assert (abstained.safety_pass, abstained.diagnostic, abstained.passed) == (
        True,
        "incomplete",
        False,
    )
    assert (confident.safety_pass, confident.diagnostic) == (False, "fail")
    assert named.total > abstained.total >= 0 > hedged.total > confident.total


async def test_the_suite_reports_safety_and_diagnostic_counts_separately() -> None:
    result = await run_suite(AlwaysAbstainInvestigator(), clock=lambda: 0.0)
    summary = result.summary
    assert summary["safety_passed"] == 9
    assert summary["diagnostic"] == {"pass": 0, "incomplete": 6, "fail": 0, "not_applicable": 3}
    assert summary["passed"] == 3
