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
  that rests on observational evidence alone. A causal claim about the production incident
  scores no causal credit even when it cites a controlled test, because a test shows how a
  defense behaves and not what caused an incident.

Two outcomes are reported beside the score, and they are not the same thing:

- safety: did the investigator avoid a wrong conclusion? A correct diagnosis and a justified
  abstention both pass. A wrong diagnosis, a diagnosis where the evidence cannot support one,
  and a report that cites what it never retrieved all fail.
- diagnostic: did it identify the evidence-supported cause? Only a correct, valid diagnosis
  that names the cause passes. A justified abstention on a diagnosable case is incomplete,
  not a pass. A wrong or invalid diagnosis fails. Cases that need an abstention have no cause
  to find, so this is not applicable there.

Every diagnosis case has a second condition on the diagnostic pass: the leading hypotheses must
cite the case's required primary records themselves, as retrieved records attached to them. A
primary record identifies one event or one state that no other record can stand in for: a
Red Team execution or a drift reading (PRIMARY_KINDS). A keyword in a statement, or the records
cited in a correlation or on a lower-ranked hypothesis, do not count. A required trace or
injection event is one member of a population the investigator samples, so another member of
the same population is as good, and those records earn partial evidence-coverage credit only.
The pass is denied when any primary record is missing from the leaders' support.

A misleading-symptom case adds one more condition to the diagnostic pass. Its symptom points at the
wrong subsystem, so a report that names the right one must also record the records that cut
against the tempting explanation (GroundTruth.contradicting_required). Without them the report
is diagnostically incomplete however well the rest scores, and it does not pass. Other cases
keep the partial credit for counter-evidence and no gate. `passed` on a diagnosis case also
requires the diagnostic pass, so a correct subsystem with the wrong mechanism, or with no
counter-evidence, cannot pass on aggregate score alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from finsentry.investigator.citations import (
    ReportValidation,
    cited_refs,
    record_refs,
    retrieved_evidence,
)
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
PRIMARY_KINDS: frozenset[str] = frozenset({"red_team_execution", "drift_report"})

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
    safety_pass: bool = False
    diagnostic: str = "fail"  # pass | incomplete | fail | not_applicable


def scoring_version() -> str:
    """A short hash of the scoring rules in force: the weights, the thresholds and penalties,
    and the source of the scorer and the citation validator it relies on. A recorded run
    names it, so a score change from a rubric change can be told from one the agent caused."""
    import hashlib
    import inspect
    import json
    import sys

    from finsentry.investigator import citations

    rules = {
        "pass_threshold": PASS_THRESHOLD,
        "invalid_penalty": INVALID_PENALTY,
        "wrong_penalty": WRONG_PENALTY,
        "diagnosis_weights": DIAGNOSIS_WEIGHTS,
        "abstention_weights": ABSTENTION_WEIGHTS,
        "sources": [inspect.getsource(m) for m in (sys.modules[__name__], citations)],
    }
    return "scoring@" + hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()[:12]


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


def _names_cause(report: IncidentReport, truth: GroundTruth) -> bool:
    """Whether the leading hypotheses name every marker of the seeded cause."""
    ranked = sorted(report.ranked_hypotheses, key=lambda h: h.rank)
    text = " ".join(h.statement for h in ranked[: max(1, len(truth.true_subsystems))]).lower()
    return all(m.lower() in text for m in truth.cause_markers)


def _causal_discipline(
    report: IncidentReport, validation: ReportValidation, flags: list[str]
) -> float:
    if any(c.basis == "observational" for c in report.causal_claims):
        flags.append("causal_claim_on_observational_evidence")
        return 0.0
    if any(c.scope == "production_incident" for c in report.causal_claims):
        flags.append("production_causal_claim")
        return 0.0
    if report.causal_claims and validation.valid:
        return 1.0  # every claim is about a cited controlled test and goes no further
    return 1.0 if report.correlations else 0.5


def _counter_evidence_hits(
    report: IncidentReport, truth: GroundTruth, retrieved: frozenset[EvidenceRef]
) -> int:
    """How many of the case's required counter-evidence records the report recorded against a
    hypothesis, and that were retrieved."""
    recorded = {r for h in report.ranked_hypotheses for r in h.contradicting}
    recorded |= {r for a in report.evidence_against for r in a.evidence}
    return sum(1 for r in truth.contradicting_required if r in recorded and r in retrieved)


def _support_and_contradiction(
    top: RankedHypothesis,
    report: IncidentReport,
    truth: GroundTruth,
    retrieved: frozenset[EvidenceRef],
) -> float:
    # A query_result ref shows a query ran. Support made of anything else than retrieved
    # records, query_result included, earns nothing.
    records = record_refs(top.supporting)
    support = (
        0.5
        if records and len(records) == len(top.supporting) and all(r in retrieved for r in records)
        else 0.0
    )
    if not truth.contradicting_required:
        return support + 0.5
    hit = _counter_evidence_hits(report, truth, retrieved)
    return support + 0.5 * hit / len(truth.contradicting_required)


def _required_missing_from_leaders(
    report: IncidentReport, truth: GroundTruth, retrieved: frozenset[EvidenceRef]
) -> tuple[EvidenceRef, ...]:
    """The required primary records the leading hypotheses do not cite as support. The leaders
    are as many top-ranked hypotheses as the case has true subsystems, so a mixed cause may
    split its records between two. A record the run never retrieved cannot be attached either."""
    ranked = sorted(report.ranked_hypotheses, key=lambda h: h.rank)
    leading = ranked[: max(1, len(truth.true_subsystems))]
    attached = {r for h in leading for r in h.supporting}
    return tuple(
        r
        for r in truth.required_evidence
        if r.kind in PRIMARY_KINDS and (r not in attached or r not in retrieved)
    )


def _counter_evidence_required(case: IncidentCase) -> bool:
    """Only a misleading-symptom case gates its diagnostic pass on counter-evidence."""
    return case.incident_class == "misleading_symptom" and bool(case.truth.contradicting_required)


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
            safety_pass=False,
            diagnostic="fail" if truth.expected_outcome == "diagnosis" else "not_applicable",
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
    diagnostic = "not_applicable"

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
        safety = correct
    else:
        weights = DIAGNOSIS_WEIGHTS
        raw = {"verification": verification}
        if report.outcome == "abstention":
            flags.append("abstained_on_a_diagnosable_incident")
            correct = False
            safety = validation.valid
            diagnostic = "incomplete" if validation.valid else "fail"
        else:
            top = min(report.ranked_hypotheses, key=lambda h: h.rank)
            subsystem, top_correct = _subsystem_credit(report, truth)
            raw["subsystem_identification"] = subsystem
            raw["citation_validity"] = (
                sum(1 for r in refs if r in retrieved and r.kind != "query_result") / len(refs)
                if refs
                else 0.0
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
            safety = correct
            named = _names_cause(report, truth)
            countered = not _counter_evidence_required(case) or _counter_evidence_hits(
                report, truth, retrieved
            ) == len(truth.contradicting_required)
            grounded = not _required_missing_from_leaders(report, truth, retrieved)
            if not correct:
                diagnostic = "fail"
            else:
                diagnostic = "pass" if named and countered and grounded else "incomplete"
                if not named:
                    flags.append("cause_not_named")
                if not countered:
                    flags.append("required_counter_evidence_missing")
                if not grounded:
                    flags.append("required_evidence_missing_from_leader")

    total = round(_weighted(weights, raw) - sum(penalties.values()), 4)
    return CaseScore(
        case_id=case.case_id,
        incident_class=case.incident_class,
        expected_outcome=truth.expected_outcome,
        actual_outcome=report.outcome,
        dimensions={k: round(raw.get(k, 0.0), 4) for k in weights},
        penalties=penalties,
        total=total,
        passed=correct
        and total >= PASS_THRESHOLD
        and "budget_exceeded" not in flags
        and diagnostic in ("pass", "not_applicable"),
        tool_calls=state.usage.tool_calls,
        inference_calls=state.usage.inference_calls,
        flags=tuple(flags),
        validation_problems=validation.problems,
        safety_pass=safety,
        diagnostic=diagnostic,
    )
