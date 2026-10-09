"""The known-answer harness: the suite is well formed, the scorer discriminates, and a
confident wrong answer scores below an abstention."""

from __future__ import annotations

import pytest

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.evaluation.cases import MISLEADING_CASE_ID, all_cases
from finsentry.investigator.evaluation.runner import run_case, run_suite
from finsentry.investigator.evaluation.scorer import PASS_THRESHOLD, CaseScore
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.stub import AlwaysAbstainInvestigator
from tests.investigator.doubles import ScriptedInvestigator, Style

CASES = {c.case_id: c for c in all_cases()}
DIAGNOSIS = [c for c in CASES.values() if c.truth.expected_outcome == "diagnosis"]
ABSTENTION = [c for c in CASES.values() if c.truth.expected_outcome == "abstention"]


async def _score(case: IncidentCase, style: Style) -> CaseScore:
    return await run_case(ScriptedInvestigator(case, style), case, lambda: 0.0)


def test_the_suite_has_six_diagnosis_classes_and_three_abstention_variants() -> None:
    assert len(DIAGNOSIS) == 6 and len(ABSTENTION) == 3
    assert {c.incident_class for c in DIAGNOSIS} == {
        "judge_degradation",
        "bad_retrieval_chunk",
        "injection_surge",
        "guardrail_regression",
        "mixed_multi_subsystem",
        "misleading_symptom",
    }
    assert {c.incident_class for c in ABSTENTION} == {"insufficient_evidence"}
    assert len(CASES) == 9, "case ids are unique"


def test_the_misleading_case_really_separates_symptom_from_cause() -> None:
    truth = CASES[MISLEADING_CASE_ID].truth
    assert truth.symptom_subsystem is not None
    assert truth.symptom_subsystem not in truth.true_subsystems
    assert truth.contradicting_required, "the evidence against the tempting answer is recorded"


def test_case_fingerprints_are_stable_and_distinct() -> None:
    first = [c.fingerprint() for c in all_cases()]
    assert first == [c.fingerprint() for c in all_cases()]
    assert len(set(first)) == 9


@pytest.mark.parametrize("case", list(CASES.values()), ids=lambda c: c.case_id)
async def test_an_ideal_investigator_scores_full_marks_on_every_case(case: IncidentCase) -> None:
    score = await _score(case, "oracle")
    assert score.passed, (score.flags, score.dimensions, score.validation_problems)
    assert score.total == pytest.approx(1.0)
    assert score.penalties == {}


async def test_the_stub_passes_only_the_abstention_cases() -> None:
    result = await run_suite(AlwaysAbstainInvestigator())
    by_id = {s.case_id: s for s in result.cases}
    assert {i for i, s in by_id.items() if s.passed} == {c.case_id for c in ABSTENTION}
    for case in DIAGNOSIS:
        s = by_id[case.case_id]
        assert not s.passed and "abstained_on_a_diagnosable_incident" in s.flags
        assert 0.0 <= s.total <= 0.10
    assert all(by_id[c.case_id].total == pytest.approx(1.0) for c in ABSTENTION)
    assert result.summary["tool_calls_total"] == 0
    assert result.summary["inference_calls_total"] == 0


async def test_a_confident_wrong_answer_scores_below_an_abstention_on_the_misleading_case() -> None:
    case = CASES[MISLEADING_CASE_ID]
    wrong = await _score(case, "confident_wrong")
    abstained = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)

    assert wrong.actual_outcome == "diagnosis" and "wrong_subsystem" in wrong.flags
    assert wrong.total < 0 <= abstained.total
    assert wrong.total < abstained.total
    assert not wrong.passed and not abstained.passed
    assert wrong.penalties["confident_wrong_diagnosis"] == 1.0


async def test_even_a_hedged_wrong_answer_cannot_beat_an_abstention() -> None:
    for case in DIAGNOSIS:
        hedged = await _score(case, "hedged_wrong")
        abstained = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)
        assert hedged.total < abstained.total, case.case_id


async def test_a_correct_abstention_beats_a_confident_diagnosis_on_insufficient_evidence() -> None:
    for case in ABSTENTION:
        correct = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)
        guessed = await _score(case, "always_diagnose")
        assert correct.passed and correct.total == pytest.approx(1.0)
        assert not guessed.passed and guessed.total < 0, case.case_id
        assert "diagnosis_on_insufficient_evidence" in guessed.flags


async def test_a_forged_citation_invalidates_the_report_and_costs_the_case() -> None:
    case = CASES["stale-chunk"]
    forged = await _score(case, "forger")
    honest = await _score(case, "oracle")
    assert "invalid_report" in forged.flags and not forged.passed
    assert any("never-retrieved-9999" in p for p in forged.validation_problems)
    assert forged.penalties["invalid_report"] == 0.5
    assert forged.total < honest.total - 0.4


async def test_a_causal_claim_on_observational_evidence_scores_below_a_hedged_one() -> None:
    case = CASES["stale-chunk"]
    hedged = await _score(case, "oracle")
    causal = await _score(case, "observational_causal")
    assert hedged.dimensions["causal_discipline"] == 1.0
    assert causal.dimensions["causal_discipline"] == 0.0
    assert "causal_claim_on_observational_evidence" in causal.flags
    assert causal.total == pytest.approx(hedged.total - 0.15)


async def test_spending_the_whole_tool_budget_lowers_the_efficiency_credit() -> None:
    case = CASES["stale-chunk"]
    lean = await _score(case, "oracle")
    spent = await _score(case, "overspender")
    assert lean.tool_calls == 4 and spent.tool_calls == 8
    assert lean.dimensions["efficiency"] == 1.0
    assert spent.dimensions["efficiency"] == pytest.approx(0.5)
    assert spent.passed  # still correct, only less efficient


async def test_the_unavailable_source_case_needs_the_unavailability_reported_not_hidden() -> None:
    case = CASES["unavailable-source"]
    score = await _score(case, "oracle")
    assert score.passed and score.tool_calls == 2
    world = FixtureWorld(case.world)
    result = await ReadOnlyAdapter(world).call(
        "get_failing_traces", "q1", failure_type="blocked", time_window_minutes=60
    )
    assert result.status == "unavailable"
    assert (await ReadOnlyAdapter(world).call("get_drift_report", "q2")).status == "ok"


async def test_an_investigator_that_raises_is_a_recorded_failure_not_a_crash() -> None:
    class Broken:
        agent_version = "broken-0"

        async def investigate(self, *_: object) -> None:
            raise RuntimeError("boom")

    score = await run_case(Broken(), CASES["judge-outage"], lambda: 0.0)  # type: ignore[arg-type]
    assert not score.passed and score.actual_outcome == "no_report"
    assert "RuntimeError: boom" in score.flags


async def test_the_recorded_result_is_reproducible_and_names_what_it_ran_against() -> None:
    first = await run_suite(AlwaysAbstainInvestigator(), clock=lambda: 0.0)
    second = await run_suite(AlwaysAbstainInvestigator(), clock=lambda: 0.0)
    assert first.to_json() == second.to_json()
    assert first.agent_version == "always-abstain-0"
    assert first.tool_contract_version.startswith("mcp-read-9@")
    assert first.pass_threshold == PASS_THRESHOLD
    assert first.suite_fingerprint and first.harness_version
