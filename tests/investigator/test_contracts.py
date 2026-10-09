"""The contracts reject malformed state and reports instead of carrying them forward."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from finsentry.investigator.contracts import (
    ABSTENTION_STATEMENT,
    Budgets,
    EvidenceRef,
    IncidentReport,
    IncidentTrigger,
    ProposedVerification,
    RankedHypothesis,
    TimeWindow,
)
from finsentry.investigator.fixtures import ANCHOR, at
from tests.investigator.helpers import make_hypothesis, make_state

VERIFY = ProposedVerification(
    kind="read_only_query", tool="get_drift_report", args={}, rationale="check the judge"
)
REF = EvidenceRef(kind="trace", record_id="t1")


def _ranked(rank: int = 1, confidence: str = "medium") -> RankedHypothesis:
    return RankedHypothesis.model_validate(
        {
            "hypothesis_id": "h1",
            "rank": rank,
            "subsystem": "retrieval",
            "statement": "a chunk is stale",
            "confidence": confidence,
            "supporting": [REF],
        }
    )


def _report(**overrides: object) -> IncidentReport:
    fields: dict[str, object] = {
        "incident_id": "inc-1",
        "outcome": "diagnosis",
        "ranked_hypotheses": [_ranked()],
        "proposed_verification": VERIFY,
        "stopping_reason": "sufficient_evidence",
    }
    fields.update(overrides)
    return IncidentReport.model_validate(fields)


def test_the_documented_starting_budgets() -> None:
    b = Budgets()
    assert (b.max_tool_calls, b.max_inference_calls, b.max_hypothesis_rounds) == (8, 2, 3)


def test_a_trigger_that_needs_a_reference_rejects_one_without() -> None:
    with pytest.raises(ValidationError, match="reference_id"):
        IncidentTrigger(kind="single_trace", description="one bad trace")
    assert IncidentTrigger(kind="error_kind_surge", description="surge").reference_id is None


def test_a_window_must_run_forward_and_rounds_minutes_up() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=ANCHOR, end=at(5))
    assert TimeWindow(start=at(90), end=ANCHOR).minutes == 90
    assert TimeWindow(start=at(0.5), end=ANCHOR).minutes == 1


def test_a_stopped_state_needs_a_reason_and_a_running_one_must_not_have_one() -> None:
    with pytest.raises(ValidationError, match="stopping_reason"):
        make_state(status="stopped")
    with pytest.raises(ValidationError, match="running"):
        make_state(stopping_reason="justified_abstention")
    assert make_state(status="stopped", stopping_reason="budget_exhausted").status == "stopped"


def test_hypothesis_status_must_be_backed_by_evidence() -> None:
    with pytest.raises(ValidationError, match="supporting"):
        make_hypothesis(status="supported")
    with pytest.raises(ValidationError, match="contradicting"):
        make_hypothesis(status="refuted")
    assert make_hypothesis(status="refuted", contradicting=[REF]).status == "refuted"


def test_a_hypothesis_must_predict_something_observable() -> None:
    with pytest.raises(ValidationError):
        make_hypothesis(predicted_observations=[])


def test_a_diagnosis_needs_ranked_hypotheses_and_no_abstention_text() -> None:
    with pytest.raises(ValidationError, match="ranked hypothesis"):
        _report(ranked_hypotheses=[])
    with pytest.raises(ValidationError, match="no abstention"):
        _report(abstention_statement=ABSTENTION_STATEMENT)


def test_ranks_must_be_contiguous_from_one() -> None:
    with pytest.raises(ValidationError, match="ranks"):
        _report(ranked_hypotheses=[_ranked(2)])


def test_an_abstention_carries_its_statement_and_makes_no_causal_claim() -> None:
    ok = _report(
        outcome="abstention",
        ranked_hypotheses=[],
        abstention_statement=ABSTENTION_STATEMENT,
        stopping_reason="justified_abstention",
    )
    assert ok.outcome == "abstention"
    with pytest.raises(ValidationError, match="abstention statement"):
        _report(outcome="abstention", ranked_hypotheses=[])
    claim = {"statement": "x caused y", "basis": "observational", "evidence": [REF]}
    with pytest.raises(ValidationError, match="causal claim"):
        _report(
            outcome="abstention",
            ranked_hypotheses=[],
            abstention_statement=ABSTENTION_STATEMENT,
            causal_claims=[claim],
        )
    with pytest.raises(ValidationError, match="low confidence"):
        _report(
            outcome="abstention",
            ranked_hypotheses=[_ranked(confidence="high")],
            abstention_statement=ABSTENTION_STATEMENT,
        )


def test_a_report_cannot_claim_its_verification_was_run() -> None:
    with pytest.raises(ValidationError):
        ProposedVerification.model_validate(
            {
                "kind": "read_only_query",
                "tool": "get_drift_report",
                "args": {},
                "rationale": "r",
                "executed": True,
            }
        )


def test_a_verification_needs_the_fields_its_kind_requires() -> None:
    with pytest.raises(ValidationError, match="scenario_id"):
        ProposedVerification(kind="red_team_scenario", rationale="r")
    with pytest.raises(ValidationError, match="tool"):
        ProposedVerification(kind="read_only_query", rationale="r")
    with pytest.raises(ValidationError):
        ProposedVerification(
            kind="read_only_query", tool="run_red_team_scenario", args={}, rationale="r"
        )  # type: ignore[arg-type]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef.model_validate({"kind": "trace", "record_id": "t1", "confidence": 0.9})
