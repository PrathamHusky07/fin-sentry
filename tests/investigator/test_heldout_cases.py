"""The frozen held-out set is well formed, solvable, and fixed.

A case is checked against a reference solution (the scripted oracle) and against the wrong
answers the scorer must fail, before the set is frozen and before any investigator runs on it.
That shows each case can be solved from what its tools return and that the scorer separates a
right answer from a wrong one on it. It says nothing about any investigator, which is run once
afterward. The manifest pins every case's fingerprint, so editing a case after the freeze fails
here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.cases_heldout import frozen_manifest, heldout_cases
from finsentry.investigator.evaluation.runner import run_case, run_suite
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.stub import AlwaysAbstainInvestigator
from tests.investigator.doubles import ScriptedInvestigator, Style

MANIFEST = (
    Path(__file__).resolve().parents[2] / "docs/measurements/investigator/heldout/frozen-cases.json"
)
CASES = heldout_cases()
DIAGNOSIS = [c for c in CASES if c.truth.expected_outcome == "diagnosis"]
ABSTENTION = [c for c in CASES if c.truth.expected_outcome == "abstention"]


async def _score(case: IncidentCase, style: Style):  # type: ignore[no-untyped-def]
    return await run_case(ScriptedInvestigator(case, style), case, lambda: 0.0)


def test_the_set_is_nine_new_instances_of_existing_classes() -> None:
    regression = {c.case_id for c in all_cases()}
    assert len(CASES) == 9 and len({c.case_id for c in CASES}) == 9
    assert not regression & {c.case_id for c in CASES}
    assert {c.incident_class for c in CASES} <= {c.incident_class for c in all_cases()}
    assert len(DIAGNOSIS) == 7 and len(ABSTENTION) == 2
    classes = {c.incident_class for c in CASES}
    assert {"mixed_multi_subsystem", "misleading_symptom", "insufficient_evidence"} <= classes


def test_the_set_is_pinned_by_the_committed_manifest() -> None:
    committed = json.loads(MANIFEST.read_text())
    assert committed["cases"] == frozen_manifest(), "a held-out case changed after the freeze"


@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_diagnosis_case_is_solvable_by_the_reference_solution(case: IncidentCase) -> None:
    score = await _score(case, "oracle")
    assert (score.safety_pass, score.diagnostic, score.passed) == (True, "pass", True)


@pytest.mark.parametrize("style", ["confident_wrong", "hedged_wrong"])
@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_wrong_diagnosis_fails_both_on_every_diagnosis_case(
    case: IncidentCase, style: Style
) -> None:
    score = await _score(case, style)
    assert (score.safety_pass, score.diagnostic) == (False, "fail")


@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_a_justified_abstention_is_safe_and_incomplete_on_a_diagnosable_case(
    case: IncidentCase,
) -> None:
    score = await run_case(AlwaysAbstainInvestigator(), case, lambda: 0.0)
    assert (score.safety_pass, score.diagnostic, score.passed) == (True, "incomplete", False)


@pytest.mark.parametrize("case", ABSTENTION, ids=lambda c: c.case_id)
async def test_an_abstention_case_rewards_abstaining_and_punishes_guessing(
    case: IncidentCase,
) -> None:
    reference = await _score(case, "oracle")
    guessed = await _score(case, "always_diagnose")
    assert (reference.safety_pass, reference.passed) == (True, True)
    assert (guessed.safety_pass, guessed.passed) == (False, False)


async def test_the_stub_is_safe_everywhere_and_passes_only_where_any_abstention_is_right() -> None:
    """The data-access case accepts only the stop that says the source was unavailable, which
    needs the source to have been tried. A stub that never queries abstains for the wrong
    reason, so it is safe there and does not pass."""
    result = await run_suite(AlwaysAbstainInvestigator(), CASES, clock=lambda: 0.0)
    assert {s.case_id for s in result.cases if s.passed} == {"ho-single-blocked-trace"}
    assert result.summary["safety_passed"] == 9
    failed = next(s for s in result.cases if s.case_id == "ho-failed-trace-queries")
    assert "abstained_for_the_wrong_reason" in failed.flags


def test_the_misleading_instance_documents_its_rule_and_seeds_the_counter_evidence() -> None:
    case = next(c for c in CASES if c.incident_class == "misleading_symptom")
    assert case.truth.contradicting_required
    assert "Diagnostic pass" in case.truth.expected_behavior
    assert case.truth.symptom_subsystem not in case.truth.true_subsystems


def test_the_data_access_failure_case_fails_on_a_live_pool_and_not_offline() -> None:
    case = next(c for c in CASES if c.case_id == "ho-failed-trace-queries")
    assert case.world.failing_queries and not case.world.unavailable


@pytest.mark.parametrize("case", DIAGNOSIS, ids=lambda c: c.case_id)
async def test_the_first_digest_holds_no_identifier_of_the_seeded_cause(case: IncidentCase) -> None:
    """A planner's first prompt is built from the trigger and the opening query only. A cause
    named by an identifier (a chunk id, a judge id) must not be in it."""
    from finsentry.investigator.adapter import ReadOnlyAdapter
    from finsentry.investigator.evaluation.planner_double import PlannerDouble
    from finsentry.investigator.evaluation.world import FixtureWorld
    from finsentry.investigator.loop import BoundedInvestigator, start_investigation

    seen: list[str] = []

    class Capture(PlannerDouble):
        async def plan(self, digest, *, round_no):  # type: ignore[no-untyped-def]
            seen.append(digest)
            return await super().plan(digest, round_no=round_no)

    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    await BoundedInvestigator(Capture()).investigate(
        state, ReadOnlyAdapter(FixtureWorld(case.world)), lambda: 0.0
    )
    identifiers = [m for m in case.truth.cause_markers if any(ch.isdigit() for ch in m) or "-" in m]
    for marker in identifiers:
        assert marker not in seen[0], marker
