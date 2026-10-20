"""A diagnostic pass needs the leading hypothesis to cite the case's required records.

ho-pii-rail-regression passed on the scorer while its cited support was a DI-001 execution, a
different scenario, because the word "PII" appeared in the statement. A keyword is not
evidence, and a record cited somewhere else in the report is not the leader's support. The
required records live in the case's ground truth, which only the scorer reads. Partial
scores stay for analysis, and the pass is denied when required evidence is missing.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import (
    Claim,
    EvidenceRef,
    InvestigationResult,
)
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.cases_heldout import heldout_cases
from finsentry.investigator.evaluation.scorer import CaseScore, score_case
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import start_investigation
from tests.investigator.doubles import ScriptedInvestigator

PII = {c.case_id: c for c in heldout_cases()}["ho-pii-rail-regression"]
MISSED = EvidenceRef(kind="red_team_execution", record_id="rt-pii-001")
CAUGHT = EvidenceRef(kind="red_team_execution", record_id="rt-pii-000")
DI = EvidenceRef(kind="red_team_execution", record_id="rt-hp-di")
OUT = EvidenceRef(kind="red_team_execution", record_id="rt-hp-out")

# The fixture reads two more executions, so a substituted record is one the run retrieved and
# a test of the gate is not also a test of the citation validator.
WIDER = replace(
    PII,
    truth=replace(
        PII.truth,
        recipe=(
            *PII.truth.recipe,
            ("list_red_team_executions", {"scenario_id": "DI-001"}),
            ("list_red_team_executions", {"scenario_id": "OUT-001"}),
        ),
        min_tool_calls=4,
    ),
)


async def _oracle(case: IncidentCase) -> InvestigationResult:
    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    return await ScriptedInvestigator(case, "oracle").investigate(
        state, ReadOnlyAdapter(FixtureWorld(case.world)), lambda: 0.0
    )


def _rewrite_support(
    result: InvestigationResult, support: list[EvidenceRef], statement: str | None = None
) -> InvestigationResult:
    """The same investigation with the leader citing `support`, in the report and in the
    ledger, so the report is internally consistent and only the gate can object."""
    ranked = [
        h.model_copy(
            update={
                "supporting": support,
                **({"statement": statement} if statement else {}),
            }
        )
        for h in result.report.ranked_hypotheses
    ]
    ledger = [
        h.model_copy(
            update={
                "supporting": support,
                **({"statement": statement} if statement else {}),
            }
        )
        for h in result.state.hypotheses
    ]
    report = result.report.model_copy(
        update={
            "ranked_hypotheses": ranked,
            "correlations": [Claim(statement="consistent with the leader", evidence=support)],
        }
    )
    return InvestigationResult(
        report=report, state=result.state.model_copy(update={"hypotheses": ledger})
    )


def _score(case: IncidentCase, result: InvestigationResult) -> CaseScore:
    return score_case(case, result, validate_report(result.report, result.state))


async def test_the_oracle_citing_both_pii_executions_passes() -> None:
    score = _score(WIDER, await _oracle(WIDER))
    assert (score.safety_pass, score.diagnostic, score.passed) == (True, "pass", True)
    assert "required_evidence_missing_from_leader" not in score.flags


@pytest.mark.parametrize(
    ("label", "support"),
    [
        ("one required record missing", [MISSED]),
        ("the other required record missing", [CAUGHT]),
        ("a different scenario's execution substituted", [DI, CAUGHT]),
        ("only an unrelated execution", [OUT]),
        ("only the DI-001 execution", [DI]),
    ],
)
async def test_a_leader_missing_a_required_record_is_not_a_diagnostic_pass(
    label: str, support: list[EvidenceRef]
) -> None:
    degraded = _rewrite_support(await _oracle(WIDER), support)
    result = _score(WIDER, degraded)
    assert result.safety_pass is True, label
    assert result.diagnostic == "incomplete", label
    assert result.passed is False, label
    assert "required_evidence_missing_from_leader" in result.flags, label


async def test_a_keyword_in_the_statement_with_the_wrong_support_does_not_pass() -> None:
    """The live failure: the statement says PII and the cited support is a DI-001 execution."""
    degraded = _rewrite_support(
        await _oracle(WIDER), [DI], statement="PII redaction no longer catches PII-001 inputs"
    )
    result = _score(WIDER, degraded)
    assert result.diagnostic == "incomplete" and not result.passed


async def test_required_records_cited_elsewhere_in_the_report_do_not_count() -> None:
    """The records appear in a correlation, not on the leading hypothesis."""
    oracle = await _oracle(WIDER)
    leader_cites_di = _rewrite_support(oracle, [DI])
    report = leader_cites_di.report.model_copy(
        update={"correlations": [Claim(statement="also seen", evidence=[MISSED, CAUGHT, DI])]}
    )
    result = _score(WIDER, InvestigationResult(report=report, state=leader_cites_di.state))
    assert result.diagnostic == "incomplete" and not result.passed


async def test_extra_support_beside_the_required_records_still_passes() -> None:
    result = _score(WIDER, _rewrite_support(await _oracle(WIDER), [MISSED, CAUGHT, DI]))
    assert (result.diagnostic, result.passed) == ("pass", True)


async def test_the_partial_score_is_kept_for_analysis() -> None:
    full = _score(WIDER, await _oracle(WIDER))
    half = _score(WIDER, _rewrite_support(await _oracle(WIDER), [MISSED]))
    assert 0 < half.dimensions["evidence_coverage"] < full.dimensions["evidence_coverage"]
    assert half.total < full.total


async def test_a_mixed_case_needs_its_records_across_both_leading_hypotheses() -> None:
    """Two true subsystems have two leaders, and the required records may be split between them."""
    mixed = {c.case_id: c for c in all_cases()}["retrieval-and-judge"]
    score = _score(mixed, await _oracle(mixed))
    assert (score.diagnostic, score.passed) == ("pass", True)


async def test_another_sampled_trace_is_as_good_as_the_one_the_case_lists() -> None:
    """A required trace is one member of a population the investigator samples. Citing a
    different member keeps the pass and loses only partial coverage credit."""
    stale = {c.case_id: c for c in all_cases()}["stale-chunk"]
    oracle = await _oracle(stale)
    full = _score(stale, oracle)
    sampled = _score(
        stale, _rewrite_support(oracle, [EvidenceRef(kind="trace", record_id="ad-01")])
    )
    assert (sampled.diagnostic, sampled.passed) == ("pass", True)
    assert sampled.dimensions["evidence_coverage"] < full.dimensions["evidence_coverage"]


async def test_the_drift_reading_of_a_misleading_case_is_a_primary_record() -> None:
    """A drift reading identifies one state, so a leader that omits it does not pass."""
    case = {c.case_id: c for c in all_cases()}["drifted-judge-misleading"]
    oracle = await _oracle(case)
    only_trace = _rewrite_support(oracle, [EvidenceRef(kind="trace", record_id="dis-01")])
    assert _score(case, only_trace).diagnostic == "incomplete"
