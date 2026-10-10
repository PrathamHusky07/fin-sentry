"""
The hypothesis ledger: how retrieved results move a hypothesis, and the deterministic
adversarial review that decides whether a leader may be reported.

assess() recomputes every hypothesis from scratch over all results, so the ledger is a pure
function of what was retrieved. A prediction is met when the evaluator saw what the hypothesis
expected, unmet when it saw the opposite, and unknown when the results cannot tell. Only
records back a status: a hypothesis is supported by records that show its predictions, and
refuted or weakened by records that show the opposite. An unmet prediction with no record
behind it (a query that matched nothing) keeps the hypothesis open and is kept on the
assessment so the review can see it.

review() challenges the leading hypothesis before anything is reported. It checks that the
leader met its own predictions, had none unmet or unknown, and that no rival for the same
symptom is also supported. It cannot prove a hypothesis true. It checks that a diagnosis
agrees with its own predictions and with the counter-evidence that was retrieved, and the
report says no more than that.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import Confidence, EvidenceRef, Hypothesis
from finsentry.investigator.signals import evaluate

MAX_DETAILS = 2


def clean(text: str) -> str:
    """Prose discipline for text a model wrote: no em-dashes."""
    return " ".join(text.replace("—", ". ").replace("–", "-").split())


@dataclass(frozen=True)
class PredictionOutcome:
    signal: str
    expect: bool
    observed: bool | None
    detail: str

    @property
    def state(self) -> Literal["met", "unmet", "unknown"]:
        if self.observed is None:
            return "unknown"
        return "met" if self.observed == self.expect else "unmet"


@dataclass(frozen=True)
class Assessment:
    hypothesis_id: str
    outcomes: tuple[PredictionOutcome, ...]

    def count(self, state: str) -> int:
        return sum(1 for o in self.outcomes if o.state == state)


def _dedupe(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    return list(dict.fromkeys(refs))


def assess(
    plan: list[Hypothesis], results: list[ToolResult]
) -> tuple[list[Hypothesis], dict[str, Assessment]]:
    """The ledger as the results leave it, and each hypothesis's per-prediction outcomes.
    plan holds the hypotheses as proposed, so a statement is never extended twice."""
    updated: list[Hypothesis] = []
    assessments: dict[str, Assessment] = {}
    for h in plan:
        supporting: list[EvidenceRef] = []
        contradicting: list[EvidenceRef] = []
        outcomes: list[PredictionOutcome] = []
        met_notes: list[str] = []
        unmet_notes: list[str] = []
        for p in h.predicted_observations:
            if p.signal is None:
                continue
            obs = evaluate(p.signal, p.subject, results)
            outcome = PredictionOutcome(p.signal, p.expect, obs.observed, obs.detail)
            outcomes.append(outcome)
            if outcome.state == "met":
                supporting += list(obs.support if p.expect else obs.against)
                met_notes.append(obs.detail)
            elif outcome.state == "unmet":
                contradicting += list(obs.against if p.expect else obs.support)
                unmet_notes.append(obs.detail)
        supporting, contradicting = _dedupe(supporting), _dedupe(contradicting)
        a = Assessment(h.hypothesis_id, tuple(outcomes))
        assessments[h.hypothesis_id] = a
        if a.count("met") and not a.count("unmet") and supporting:
            status = "supported"
        elif a.count("unmet") and contradicting:
            status = "weakened" if a.count("met") else "refuted"
        else:
            status = "open"
        statement = clean(h.statement)
        met_notes, unmet_notes = list(dict.fromkeys(met_notes)), list(dict.fromkeys(unmet_notes))
        if status == "supported" and met_notes:
            statement += f" Observed: {'; '.join(met_notes[:MAX_DETAILS])}."
        elif status in ("refuted", "weakened") and unmet_notes:
            statement += f" Contradicted: {'; '.join(unmet_notes[:MAX_DETAILS])}."
        updated.append(
            h.model_copy(
                update={
                    "statement": statement,
                    "supporting": supporting,
                    "contradicting": contradicting,
                    "status": status,
                }
            )
        )
    return updated, assessments


@dataclass(frozen=True)
class Review:
    decision: Literal["diagnose", "abstain", "continue"]
    leaders: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # what the challenge found, kept in the report
    unresolved: tuple[str, ...] = ()  # what is still unknown, kept as missing evidence
    confidence: dict[str, Confidence] = field(default_factory=dict)


def _unknowns(h: Hypothesis, a: Assessment) -> list[str]:
    return [
        f"{h.hypothesis_id} ({h.subsystem}): {o.signal} could not be told, {o.detail}"
        for o in a.outcomes
        if o.state == "unknown"
    ]


def review(
    ledger: list[Hypothesis],
    assessments: dict[str, Assessment],
    *,
    can_continue: bool,
    unverified_empties: bool,
) -> Review:
    groups: dict[str, list[Hypothesis]] = defaultdict(list)
    for h in ledger:
        groups[h.symptom].append(h)

    leaders: list[Hypothesis] = []
    notes: list[str] = []
    unresolved: list[str] = []
    conflict = False
    confidence: dict[str, Confidence] = {}
    for symptom, members in groups.items():
        supported = [h for h in members if h.status == "supported"]
        for h in members:
            unresolved += _unknowns(h, assessments[h.hypothesis_id])
        if len(supported) > 1:
            conflict = True
            ids = ", ".join(h.hypothesis_id for h in supported)
            unresolved.append(f"{ids} are each supported for the same symptom ({symptom})")
            continue
        if not supported:
            unresolved.append(f"no hypothesis for {symptom} is supported by the retrieved records")
            continue
        lead = supported[0]
        a = assessments[lead.hypothesis_id]
        if a.count("unknown"):
            notes.append(
                f"{lead.hypothesis_id} led {symptom} but had a prediction it could not check"
            )
            continue
        refuted = [h for h in members if h is not lead and h.status in ("refuted", "weakened")]
        untested = [h for h in members if h is not lead and h.status == "open"]
        leaders.append(lead)
        rival_text = ", ".join(
            f"{h.hypothesis_id} {h.status} by {len(h.contradicting)} record"
            + ("s" if len(h.contradicting) != 1 else "")
            for h in refuted
        )
        notes.append(
            f"Challenge of {lead.hypothesis_id} for {symptom}: met {a.count('met')} of "
            f"{len(a.outcomes)} predictions with none unmet. "
            + (f"Rivals: {rival_text}. " if refuted else "No rival was refuted by a record. ")
            + (
                f"Rivals {', '.join(h.hypothesis_id for h in untested)} stayed open. "
                if untested
                else ""
            )
        )
        high = bool(refuted) and not unverified_empties
        confidence[lead.hypothesis_id] = (
            "high" if high else "medium" if (refuted or len(lead.supporting) > 1) else "low"
        )
        if unverified_empties and confidence[lead.hypothesis_id] == "high":
            confidence[lead.hypothesis_id] = "medium"

    unresolved = list(dict.fromkeys(unresolved))
    leaders.sort(key=lambda h: (-assessments[h.hypothesis_id].count("met"), h.hypothesis_id))
    if conflict and can_continue:
        return Review("continue", unresolved=tuple(unresolved), notes=tuple(notes))
    if conflict:
        return Review("abstain", notes=tuple(notes), unresolved=tuple(unresolved))
    if leaders:
        return Review(
            "diagnose",
            tuple(h.hypothesis_id for h in leaders),
            tuple(notes),
            tuple(unresolved),
            confidence,
        )
    undecided = any(h.status == "open" for h in ledger)
    if can_continue and undecided:
        return Review("continue", unresolved=tuple(unresolved), notes=tuple(notes))
    return Review("abstain", notes=tuple(notes), unresolved=tuple(unresolved))
