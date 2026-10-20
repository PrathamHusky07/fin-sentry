"""
Turns a reviewed ledger into an IncidentReport, and picks the one verification it proposes.

The report keeps observation, correlation and causation apart. A diagnosis is written as a
correlation ("consistent with") and never as a causal claim, because the stored records
cannot establish what caused an incident. Every cited ref comes from a query this
investigation ran, and the report carries the review's note on what it did and did not check.
"""

from __future__ import annotations

from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.citations import STATUS_ORDER, verification_problems
from finsentry.investigator.contracts import (
    Claim,
    EvidenceAgainst,
    Hypothesis,
    IncidentReport,
    InvestigationState,
    ProposedVerification,
    RankedHypothesis,
    StoppingReason,
    Subsystem,
)
from finsentry.investigator.ledger import Assessment, Review, Scopes, observe
from finsentry.investigator.reports import default_verification
from finsentry.redteam.registry import get_scenario

# The Red Team scenario that exercises the layer a subsystem names, when one exists.
SCENARIO_FOR: dict[Subsystem, str] = {
    "input_rails": "DI-001",
    "retrieval": "IND-001",
    "output_rails": "OUT-001",
}
REVIEW_LIMIT = (
    "The review checks a diagnosis against its own predictions and the counter-evidence that "
    "was retrieved. It does not prove the cause."
)


def choose_verification(
    state: InvestigationState, subsystem: Subsystem | None, draft: ProposedVerification | None
) -> ProposedVerification:
    """One step to propose, never executed: the planner's if it is valid, else the scenario
    for the leading subsystem, else an unrun read-only query."""
    if draft is not None and not verification_problems(draft, state):
        return draft
    scenario = SCENARIO_FOR.get(subsystem) if subsystem else None
    if scenario and get_scenario(scenario) is not None:
        return ProposedVerification(
            kind="red_team_scenario",
            scenario_id=scenario,
            rationale=f"Exercise the {subsystem} defenses with a controlled input and compare "
            "the result with the incident.",
        )
    return default_verification(state)


def _limitations(state: InvestigationState, review: Review, results: list[ToolResult]) -> list[str]:
    notes = [f"{g.source}: {g.detail}" for g in state.known_data_gaps]
    notes += list(review.notes)
    unverified = [r.query_id for r in results if r.empty_unverified]
    if unverified:
        notes.append(
            f"{', '.join(unverified)} returned no rows, which cannot be told from a failed "
            "query over this transport, so none of it is read as a clean signal."
        )
    return [*notes, REVIEW_LIMIT]


def _missing(review: Review, state: InvestigationState) -> list[str]:
    missing = list(review.unresolved)
    missing += [q for q in state.unresolved_questions if q not in missing]
    return missing


def _rank(ledger: list[Hypothesis], review: Review) -> list[Hypothesis]:
    lead = [h for i in review.leaders for h in ledger if h.hypothesis_id == i]
    rest = sorted(
        (h for h in ledger if h.hypothesis_id not in review.leaders),
        key=lambda h: STATUS_ORDER[h.status],
    )
    return [*lead, *rest]


def build_diagnosis(
    state: InvestigationState,
    ledger: list[Hypothesis],
    assessments: dict[str, Assessment],
    review: Review,
    results: list[ToolResult],
    verification: ProposedVerification | None,
    notes: list[str],
    scopes: Scopes | None = None,
) -> IncidentReport:
    ordered = _rank(ledger, review)
    ranked = [
        RankedHypothesis(
            hypothesis_id=h.hypothesis_id,
            rank=i,
            subsystem=h.subsystem,
            statement=h.statement,
            confidence=review.confidence.get(h.hypothesis_id, "low"),
            supporting=h.supporting,
            contradicting=h.contradicting,
        )
        for i, h in enumerate(ordered, 1)
    ]
    leaders = [h for h in ordered if h.hypothesis_id in review.leaders]
    observations: list[Claim] = []
    for h in leaders:
        for p in h.predicted_observations:
            obs = observe(h, p, results, scopes)
            records = list(obs.support if obs and p.expect else obs.against if obs else [])
            if obs and obs.observed == p.expect and records:
                observations.append(Claim(statement=obs.detail, evidence=records))
    against = [
        EvidenceAgainst(
            hypothesis_id=h.hypothesis_id,
            statement=f"Retrieved records cut against {h.hypothesis_id} ({h.subsystem}).",
            evidence=h.contradicting,
        )
        for h in ordered
        if h.contradicting
    ]
    return IncidentReport(
        incident_id=state.incident_id,
        outcome="diagnosis",
        ranked_hypotheses=ranked,
        observations=observations,
        correlations=[
            Claim(statement=f"Consistent with: {h.statement}", evidence=h.supporting)
            for h in leaders
        ],
        missing_evidence=_missing(review, state),
        evidence_against=against,
        tool_unavailable=sorted(
            {q.tool for q in state.executed_queries if q.status == "unavailable"}
        ),
        empty_results=[q.query_id for q in state.executed_queries if q.status == "empty"],
        tests_actually_run=[q.query_id for q in state.executed_queries],
        proposed_verification=choose_verification(state, leaders[0].subsystem, verification),
        limitations=[*_limitations(state, review, results), *notes],
        stopping_reason=_reason(state),
    )


def _reason(state: InvestigationState) -> StoppingReason:
    if state.stopping_reason is None:
        raise ValueError("a report needs a stopped investigation")
    return state.stopping_reason
