"""Day 11.1 evidence-boundary fixes. Each test here was written to fail against the Day 11.0
contracts and pass once the boundary is closed."""

from __future__ import annotations

import pytest

from finsentry.investigator import fixtures as fx
from finsentry.investigator.adapter import ReadOnlyAdapter, interpret
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import (
    EvidenceRef,
    ExecutedQuery,
    IncidentReport,
    InvestigationResult,
    InvestigationState,
    ProposedVerification,
)
from finsentry.investigator.evaluation.cases import all_cases
from finsentry.investigator.evaluation.scorer import CaseScore, score_case
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.evaluation.world import FixtureWorld
from finsentry.investigator.loop import start_investigation
from finsentry.investigator.policy import (
    PolicyViolationError,
    admit_inference,
    admit_query,
    finish,
    record_hypothesis_round,
    record_query,
    with_elapsed,
)
from finsentry.investigator.reports import abstention_report, default_verification
from finsentry.mcp.tools.drift import TransitionRecordSummary
from tests.investigator.doubles import ScriptedInvestigator
from tests.investigator.helpers import make_hypothesis, make_state

CASES = {c.case_id: c for c in all_cases()}
REAL = EvidenceRef(kind="trace", record_id="t-real")
SECOND = EvidenceRef(kind="trace", record_id="t-second")
QUERY = EvidenceRef(kind="query_result", record_id="q1")
VERIFY = ProposedVerification(
    kind="read_only_query", tool="get_drift_report", args={}, rationale="read the last canary"
)


def _query(
    query_id: str, status: str, evidence: list[EvidenceRef], **args: object
) -> ExecutedQuery:
    return ExecutedQuery(
        query_id=query_id,
        tool="get_failing_traces",
        args={"limit": int(query_id[1:]), **args},
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
    )


def _investigated(*, ledger: list | None = None) -> InvestigationState:
    """q1 returned t-real, q2 matched nothing. The ledger holds a supported h1 and an open h2."""
    h1 = make_hypothesis("h1", supporting=[REAL], status="supported")
    h2 = make_hypothesis("h2", subsystem="judges", statement="the judge is degraded")
    state = make_state(hypotheses=ledger if ledger is not None else [h1, h2])
    state = record_query(state, _query("q1", "ok", [QUERY, REAL, SECOND]), 1.0)
    state = record_query(
        state, _query("q2", "empty", [EvidenceRef(kind="query_result", record_id="q2")]), 1.0
    )
    return finish(state, "sufficient_evidence")


def _ranked(hid: str, rank: int, subsystem: str, **extra: object) -> dict[str, object]:
    return {
        "hypothesis_id": hid,
        "rank": rank,
        "subsystem": subsystem,
        "statement": f"{hid} statement",
        "confidence": "medium",
        **extra,
    }


def _diagnosis(**overrides: object) -> IncidentReport:
    fields: dict[str, object] = {
        "incident_id": "inc-1",
        "outcome": "diagnosis",
        "ranked_hypotheses": [
            _ranked("h1", 1, "retrieval", supporting=[REAL]),
            _ranked("h2", 2, "judges"),
        ],
        "correlations": [{"statement": "consistent with a shared chunk", "evidence": [REAL]}],
        "tests_actually_run": ["q1", "q2"],
        "empty_results": ["q2"],
        "proposed_verification": VERIFY,
        "stopping_reason": "sufficient_evidence",
    }
    fields.update(overrides)
    return IncidentReport.model_validate(fields)


def test_the_reference_report_is_valid() -> None:
    result = validate_report(_diagnosis(), _investigated())
    assert result.valid, result.problems


# 1. query_result is provenance, never evidence for a material claim.


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "ranked_hypotheses": [
                _ranked("h1", 1, "retrieval", supporting=[QUERY]),
                _ranked("h2", 2, "judges"),
            ]
        },
        {
            "ranked_hypotheses": [
                _ranked("h1", 1, "retrieval", supporting=[REAL], contradicting=[QUERY]),
                _ranked("h2", 2, "judges"),
            ]
        },
        {"correlations": [{"statement": "consistent with a shared chunk", "evidence": [QUERY]}]},
        {
            "evidence_against": [
                {"hypothesis_id": "h2", "statement": "cuts against", "evidence": [QUERY]}
            ]
        },
        {
            "causal_claims": [
                {"statement": "x caused y", "basis": "observational", "evidence": [QUERY]}
            ]
        },
    ],
    ids=["supporting", "contradicting", "correlation", "evidence_against", "causal_claim"],
)
def test_a_query_result_ref_cannot_back_a_material_claim(overrides: dict[str, object]) -> None:
    result = validate_report(_diagnosis(**overrides), _investigated())
    assert not result.valid
    assert any("query_result" in p for p in result.problems), result.problems


async def test_a_query_result_only_top_hypothesis_is_invalid_and_earns_no_support() -> None:
    case = CASES["judge-outage"]
    honest = await _scored_variant(case, lambda top, q: top.supporting)
    provenance = await _scored_variant(case, lambda top, q: [q])
    assert provenance[1].problems and any("query_result" in p for p in provenance[1].problems)
    assert not provenance[1].valid and honest[1].valid
    assert honest[0].dimensions["supporting_and_contradicting"] == 1.0
    assert provenance[0].dimensions["supporting_and_contradicting"] == 0.5
    assert (
        provenance[0].dimensions["evidence_coverage"] <= honest[0].dimensions["evidence_coverage"]
    )


async def _scored_variant(case: IncidentCase, support):  # type: ignore[no-untyped-def]
    """Run the ideal investigator, then swap what the top hypothesis cites."""
    state = start_investigation(f"inc-{case.case_id}", case.trigger, case.window, scope=case.scope)
    result = await ScriptedInvestigator(case, "oracle").investigate(
        state, ReadOnlyAdapter(FixtureWorld(case.world)), lambda: 0.0
    )
    query_ref = next(
        r for q in result.state.executed_queries for r in q.evidence if r.kind == "query_result"
    )
    top, *rest = result.report.ranked_hypotheses
    changed = top.model_copy(update={"supporting": support(top, query_ref)})
    report = result.report.model_copy(update={"ranked_hypotheses": [changed, *rest]})
    variant = InvestigationResult(report=report, state=result.state)
    validation = validate_report(report, variant.state)
    return score_case(case, variant, validation), validation


# 3. Every action gate honors the terminal conditions.


def _critically_unavailable() -> InvestigationState:
    """A faithfulness_block_cluster whose critical tool, get_failing_traces, failed twice."""
    args: dict[str, object] = {"failure_type": "blocked", "limit": 50}

    def attempt(query_id: str, why: str | None) -> ExecutedQuery:
        return ExecutedQuery(
            query_id=query_id,
            tool="get_failing_traces",
            args=args,
            status="unavailable",
            error="RisingWave reported offline",
            retry_justification=why,
        )

    state = record_query(make_state(), attempt("q1", None), 0.1)
    return record_query(state, attempt("q2", "the source may have recovered"), 0.2)


def _gate_states() -> dict[str, InvestigationState]:
    return {
        "wall_clock": with_elapsed(make_state(), 121.0),
        "critical_unavailable": _critically_unavailable(),
        "stopped": finish(make_state(), "justified_abstention"),
    }


@pytest.mark.parametrize("name", ["wall_clock", "critical_unavailable", "stopped"])
def test_inference_is_refused_in_every_terminal_state(name: str) -> None:
    assert not admit_inference(_gate_states()[name]).allowed


@pytest.mark.parametrize("name", ["wall_clock", "critical_unavailable", "stopped"])
def test_a_hypothesis_round_is_refused_in_every_terminal_state(name: str) -> None:
    with pytest.raises(PolicyViolationError):
        record_hypothesis_round(_gate_states()[name], [make_hypothesis("h1")])


def test_a_query_is_refused_once_a_critical_source_is_unavailable() -> None:
    state = _critically_unavailable()
    assert not admit_query(state, "get_drift_report", {}).allowed


# 4. A controlled test says something about the test, not about the production incident.


async def _oracle(case_id: str) -> tuple[IncidentCase, InvestigationResult]:
    case = CASES[case_id]
    state = start_investigation(f"inc-{case_id}", case.trigger, case.window, scope=case.scope)
    result = await ScriptedInvestigator(case, "oracle").investigate(
        state, ReadOnlyAdapter(FixtureWorld(case.world)), lambda: 0.0
    )
    return case, result


def _with_causal(result: InvestigationResult, **claim: object) -> InvestigationResult:
    evidence = [EvidenceRef(kind="red_team_execution", record_id="rt-out-001")]
    causal = {
        "statement": "the schema rail fails on malformed output",
        "basis": "controlled_test",
        "evidence": evidence,
        **claim,
    }
    report = IncidentReport.model_validate(
        {**result.report.model_dump(), "causal_claims": [causal]}
    )
    return InvestigationResult(report=report, state=result.state)


async def _score(case: IncidentCase, result: InvestigationResult) -> tuple[CaseScore, bool]:
    validation = validate_report(result.report, result.state)
    return score_case(case, result, validation), validation.valid


async def test_a_production_cause_resting_on_a_controlled_test_earns_no_causal_credit() -> None:
    case, result = await _oracle("schema-rail-regression")
    hedged, hedged_valid = await _score(case, result)
    overclaim, overclaim_valid = await _score(
        case, _with_causal(result, scope="production_incident")
    )
    assert hedged_valid and hedged.dimensions["causal_discipline"] == 1.0
    assert not overclaim_valid
    assert overclaim.dimensions["causal_discipline"] < 1.0
    assert "production_causal_claim" in overclaim.flags
    assert overclaim.total < hedged.total


async def test_a_claim_scoped_to_the_test_itself_is_allowed() -> None:
    case, result = await _oracle("schema-rail-regression")
    scoped, valid = await _score(case, _with_causal(result, scope="test_behavior"))
    assert valid, scoped.validation_problems
    assert scoped.dimensions["causal_discipline"] == 1.0


# 5. The default verification never proposes a step already run.


def test_the_default_verification_is_valid_even_when_every_candidate_was_run() -> None:
    state = make_state()
    for n in (1, 2):  # a faithfulness cluster has one trigger-specific step and one fallback
        step = default_verification(state)
        state = record_query(
            state,
            ExecutedQuery(
                query_id=f"q{n}",
                tool=step.tool,  # type: ignore[arg-type]
                args=step.args or {},
                status="empty",
                evidence=[EvidenceRef(kind="query_result", record_id=f"q{n}")],
            ),
            0.0,
        )
    stopped = finish(state, "justified_abstention")
    report = abstention_report(stopped)
    assert report.proposed_verification.kind == "none_available"
    assert validate_report(report, stopped).valid


def test_none_available_is_rejected_while_an_unrun_candidate_remains() -> None:
    state = finish(make_state(), "justified_abstention")
    claim = ProposedVerification(kind="none_available", rationale="nothing left")
    report = abstention_report(state).model_copy(update={"proposed_verification": claim})
    assert any("none_available" in p for p in validate_report(report, state).problems)


# 6. The report and the investigation's ledger agree.


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"tests_actually_run": ["q1"]}, "q2"),
        ({"tests_actually_run": ["q1", "q2", "q2"]}, "more than once"),
        ({"empty_results": []}, "q2"),
        ({"empty_results": ["q2", "q2"]}, "more than once"),
        ({"ranked_hypotheses": [_ranked("h1", 1, "retrieval", supporting=[REAL])]}, "h2"),
        (
            {
                "ranked_hypotheses": [
                    _ranked("h1", 1, "retrieval", supporting=[REAL]),
                    _ranked("h1", 2, "retrieval", supporting=[REAL]),
                ]
            },
            "more than once",
        ),
        (
            {
                "ranked_hypotheses": [
                    _ranked("h1", 1, "judges", supporting=[REAL]),
                    _ranked("h2", 2, "judges"),
                ]
            },
            "subsystem",
        ),
        (
            {
                "ranked_hypotheses": [
                    _ranked("h1", 1, "retrieval", supporting=[REAL, SECOND]),
                    _ranked("h2", 2, "judges"),
                ]
            },
            "ledger",
        ),
    ],
    ids=[
        "run_omits_a_query",
        "run_duplicate",
        "empty_omits_a_query",
        "empty_duplicate",
        "ranking_omits_a_hypothesis",
        "ranking_duplicate",
        "subsystem_differs",
        "support_not_in_ledger",
    ],
)
def test_the_report_must_match_the_investigations_ledger(
    overrides: dict[str, object], needle: str
) -> None:
    result = validate_report(_diagnosis(**overrides), _investigated())
    assert not result.valid
    assert any(needle in p for p in result.problems), result.problems


def test_the_report_may_not_list_a_non_empty_query_as_empty() -> None:
    result = validate_report(_diagnosis(empty_results=["q1", "q2"]), _investigated())
    assert any("q1" in p and "not an empty result" in p for p in result.problems)


def test_a_refuted_hypothesis_cannot_lead_the_report() -> None:
    h1 = make_hypothesis("h1", contradicting=[REAL], status="refuted")
    h2 = make_hypothesis("h2", subsystem="judges", supporting=[REAL], status="supported")
    state = _investigated(ledger=[h1, h2])
    report = _diagnosis(
        ranked_hypotheses=[
            _ranked("h1", 1, "retrieval", supporting=[REAL]),
            _ranked("h2", 2, "judges", supporting=[REAL]),
        ]
    )
    assert any("refuted" in p for p in validate_report(report, state).problems)


# 7. A drift report with transition history but no latest reading is not empty.


def test_drift_transition_history_is_evidence_even_without_a_latest_reading() -> None:
    history = [
        TransitionRecordSummary(
            observed_at=fx.at(40).isoformat(),
            previous_state="healthy",
            new_state="drifted",
            previous_mode="normal",
            new_mode="normal",
            reason="kappa fell below the entry threshold",
            kappa=0.31,
        )
    ]
    status, evidence, _ = interpret(
        "get_drift_report", fx.drift_report(state=None, transitions=history), "q1"
    )
    assert status == "ok"
    assert EvidenceRef(kind="drift_report", record_id="gemini-rubric") in evidence


def test_drift_with_no_reading_and_no_history_is_still_empty() -> None:
    status, _, _ = interpret("get_drift_report", fx.drift_report(state=None), "q1")
    assert status == "empty"
