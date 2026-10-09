"""
Scoring for one known-answer case. Pure and deterministic: no model grades anything.

Diagnosis cases are scored on seven dimensions. Abstention cases are scored on four. A report
that cites a record no query returned is invalid and loses half a point on top of whatever
else it scored.

The ordering the harness guarantees by construction:

- A diagnosis whose top hypothesis names the wrong subsystem earns no credit for subsystem,
  coverage, support, causal discipline or efficiency, so it can score at most 0.20
  (citation hygiene plus the verification step). It then loses a penalty set by its stated
  confidence, 0.35 at the least. A confident wrong answer therefore always scores below zero.
- An abstention on a case that needed a diagnosis scores at most 0.10 and never below zero.
  On a case where the evidence cannot support a cause, a correct abstention scores near 1.
- Within a correct diagnosis, a hedged "consistent with" claim scores above a causal claim
  that rests on observational evidence alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from finsentry.investigator.citations import ReportValidation, cited_refs, retrieved_evidence
from finsentry.investigator.contracts import (
    Confidence,
    EvidenceRef,
    IncidentReport,
    InvestigationResult,
    InvestigationState,
    RankedHypothesis,
)
from finsentry.investigator.evaluation.types import GroundTruth, IncidentCase

PASS_THRESHOLD = 0.75
INVALID_PENALTY = 0.5
WRONG_PENALTY: dict[Confidence, float] = {"high": 1.0, "medium": 0.7, "low": 0.35}

DIAGNOSIS_WEIGHTS = {
    "subsystem_identification": 0.25,
    "evidence_coverage": 0.15,
    "citation_validity": 0.10,
    "supporting_and_contradicting": 0.10,
    "causal_discipline": 0.15,
    "verification": 0.10,
    "efficiency": 0.15,
}
ABSTENTION_WEIGHTS = {
    "correct_abstention": 0.60,
    "honest_reporting": 0.15,
    "verification": 0.10,
    "efficiency": 0.15,
}


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    incident_class: str
    expected_outcome: str
    actual_outcome: str
    dimensions: dict[str, float]
    penalties: dict[str, float]
    total: float
    passed: bool
    tool_calls: int
    inference_calls: int
    flags: tuple[str, ...]
    validation_problems: tuple[str, ...]


def _efficiency(state: InvestigationState, min_calls: int, flags: list[str]) -> float:
    calls, budget = state.usage.tool_calls, state.budgets.max_tool_calls
    if calls > budget or state.usage.inference_calls > state.budgets.max_inference_calls:
        flags.append("budget_exceeded")
        return 0.0
    allowance = min_calls + 1
    if calls <= allowance:
        return 1.0
    return max(0.5, 1 - 0.5 * (calls - allowance) / max(1, budget - allowance))


def _verification(
    report: IncidentReport, truth: GroundTruth, validation: ReportValidation
) -> float:
    if any("proposed" in p for p in validation.problems):
        return 0.0
    v = report.proposed_verification
    if v.kind == "red_team_scenario":
        return 1.0 if v.scenario_id in truth.acceptable_scenarios else 0.0
    return 1.0 if v.tool in truth.acceptable_tools else 0.0


def _subsystem_credit(report: IncidentReport, truth: GroundTruth) -> tuple[float, bool]:
    """Credit and whether the top hypothesis names a true subsystem."""
    ranked = sorted(report.ranked_hypotheses, key=lambda h: h.rank)
    top_correct = bool(ranked) and ranked[0].subsystem in truth.true_subsystems
    if not top_correct:
        return 0.0, False
    leading = ranked[: len(truth.true_subsystems)]
    predicted = {h.subsystem for h in leading}
    jaccard = len(predicted & truth.true_subsystems) / len(predicted | truth.true_subsystems)
    if not truth.cause_markers:
        return jaccard, True
    text = " ".join(h.statement for h in leading).lower()
    found = sum(1 for m in truth.cause_markers if m.lower() in text)
    return 0.7 * jaccard + 0.3 * found / len(truth.cause_markers), True


def _causal_discipline(
    report: IncidentReport, validation: ReportValidation, flags: list[str]
) -> float:
    if any(c.basis == "observational" for c in report.causal_claims):
        flags.append("causal_claim_on_observational_evidence")
        return 0.0
    if report.causal_claims and validation.valid:
        return 1.0  # every remaining causal claim rests on a cited controlled test
    return 1.0 if report.correlations else 0.5


def _support_and_contradiction(
    top: RankedHypothesis,
    report: IncidentReport,
    truth: GroundTruth,
    retrieved: frozenset[EvidenceRef],
) -> float:
    support = 0.5 if top.supporting and all(r in retrieved for r in top.supporting) else 0.0
    if not truth.contradicting_required:
        return support + 0.5
    recorded = {r for h in report.ranked_hypotheses for r in h.contradicting}
    recorded |= {r for a in report.evidence_against for r in a.evidence}
    hit = sum(1 for r in truth.contradicting_required if r in recorded and r in retrieved)
    return support + 0.5 * hit / len(truth.contradicting_required)


def _weighted(weights: dict[str, float], raw: dict[str, float]) -> float:
    return sum(weights[name] * raw.get(name, 0.0) for name in weights)


def score_case(
    case: IncidentCase,
    result: InvestigationResult | None,
    validation: ReportValidation | None,
    error: str | None = None,
) -> CaseScore:
    truth = case.truth
    if result is None or validation is None:
        return CaseScore(
            case.case_id,
            case.incident_class,
            truth.expected_outcome,
            "no_report",
            {},
            {},
            0.0,
            False,
            0,
            0,
            ("investigator_error", error or "no report"),
            (),
        )
    report, state = result.report, result.state
    retrieved = retrieved_evidence(state)
    refs = cited_refs(report)
    flags: list[str] = []
    penalties: dict[str, float] = {}
    if not validation.valid:
        penalties["invalid_report"] = INVALID_PENALTY
        flags.append("invalid_report")

    verification = _verification(report, truth, validation)
    top: RankedHypothesis | None = None
    top_correct = False

    if truth.expected_outcome == "abstention":
        weights = ABSTENTION_WEIGHTS
        raw: dict[str, float] = {}
        if report.outcome == "abstention":
            stops = truth.acceptable_stops
            stop_ok = not stops or report.stopping_reason in stops
            raw["correct_abstention"] = (1.0 if stop_ok else 0.5) if validation.valid else 0.0
            raw["honest_reporting"] = 1.0 if validation.valid else 0.0
            raw["verification"] = verification
            if raw["correct_abstention"] > 0:
                raw["efficiency"] = _efficiency(state, truth.min_tool_calls, flags)
            if not stop_ok:
                flags.append("abstained_for_the_wrong_reason")
        else:
            top = min(report.ranked_hypotheses, key=lambda h: h.rank)
            penalties["diagnosed_where_evidence_was_insufficient"] = WRONG_PENALTY[top.confidence]
            flags.append("diagnosis_on_insufficient_evidence")
        correct = report.outcome == "abstention" and validation.valid
    else:
        weights = DIAGNOSIS_WEIGHTS
        raw = {"verification": verification}
        if report.outcome == "abstention":
            flags.append("abstained_on_a_diagnosable_incident")
            correct = False
        else:
            top = min(report.ranked_hypotheses, key=lambda h: h.rank)
            subsystem, top_correct = _subsystem_credit(report, truth)
            raw["subsystem_identification"] = subsystem
            raw["citation_validity"] = (
                sum(1 for r in refs if r in retrieved) / len(refs) if refs else 0.0
            )
            if top_correct:
                required = truth.required_evidence
                cited = set(refs) & retrieved
                raw["evidence_coverage"] = (
                    sum(1 for r in required if r in cited) / len(required) if required else 1.0
                )
                raw["supporting_and_contradicting"] = _support_and_contradiction(
                    top, report, truth, retrieved
                )
                raw["causal_discipline"] = _causal_discipline(report, validation, flags)
                raw["efficiency"] = _efficiency(state, truth.min_tool_calls, flags)
            else:
                penalties["confident_wrong_diagnosis"] = WRONG_PENALTY[top.confidence]
                flags.append("wrong_subsystem")
            correct = top_correct and validation.valid

    total = round(_weighted(weights, raw) - sum(penalties.values()), 4)
    return CaseScore(
        case_id=case.case_id,
        incident_class=case.incident_class,
        expected_outcome=truth.expected_outcome,
        actual_outcome=report.outcome,
        dimensions={k: round(raw.get(k, 0.0), 4) for k in weights},
        penalties=penalties,
        total=total,
        passed=correct and total >= PASS_THRESHOLD and "budget_exceeded" not in flags,
        tool_calls=state.usage.tool_calls,
        inference_calls=state.usage.inference_calls,
        flags=tuple(flags),
        validation_problems=validation.problems,
    )
