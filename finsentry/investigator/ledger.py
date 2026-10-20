"""
The hypothesis ledger: how retrieved results move a hypothesis, and the deterministic
adversarial review that decides whether a leader may be reported.

assess() recomputes every hypothesis from scratch, so the ledger is a pure function of what was
retrieved. Each prediction is judged by the results of the query it names (its query_key),
looked up in `scopes`, and by nothing else: another endpoint, time window, scenario or sampled
population cannot satisfy or contradict it, and a query that never ran leaves it unknown.

A prediction is met when the evaluator saw what the hypothesis expected, unmet when it saw the
opposite, and unknown when the results cannot tell. Only records back a status: a hypothesis is
supported by records that show its predictions, and refuted or weakened by records that show
the opposite. An unmet prediction with no record behind it (a query that matched nothing)
keeps the hypothesis open and is kept on the assessment so the review can see it.

review() challenges the leading hypothesis before anything is reported. It checks that the
leader met its own predictions, had none unmet or unknown, and that no rival for the same
symptom is also supported. It cannot prove a hypothesis true. It checks that a diagnosis
agrees with its own predictions and with the counter-evidence that was retrieved, and the
report says no more than that.

assess() also checks, conservatively, that the records behind a present signal can bear on the
subsystem the hypothesis names (Observation.subsystems). A chunk finding cannot show a fault in
the output rails however well it is cited, so that prediction is set aside and recorded as
rejected. A finding that fits several subsystems supports every hypothesis it fits, and the
review then finds two supported rivals and names neither.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import (
    Confidence,
    EvidenceRef,
    Hypothesis,
    PredictedObservation,
    Signal,
    TriggerKind,
)
from finsentry.investigator.signals import POOLED_SIGNALS, Observation, evaluate

MAX_DETAILS = 2

# The signals a trigger already states. A block cluster was reported because requests were
# blocked, so seeing blocks again shows the incident exists and says nothing about why.
SYMPTOM_SIGNALS: dict[TriggerKind, frozenset[Signal]] = {
    "faithfulness_block_cluster": frozenset({"block_cluster"}),
    "error_kind_surge": frozenset({"error_cluster"}),
    "drift_degradation": frozenset({"judge_drift"}),
    "judge_disagreement_cluster": frozenset(),
    "red_team_miss": frozenset(),
    "single_trace": frozenset(),
}


def clean(text: str) -> str:
    """Prose discipline for text a model wrote: no em-dashes."""
    return " ".join(text.replace("—", ". ").replace("–", "-").split())


# The query ids each query_key covers: the executed queries that made the same call, and for a
# sampled group the traces the loop took from its listing.
Scopes = dict[str, frozenset[str]]


def covered_queries(
    h: Hypothesis, p: PredictedObservation, scopes: Scopes | None
) -> frozenset[str] | None:
    """The executed queries a prediction is judged by. None means every result, for a
    prediction that names no query or when no scopes were given. A prediction about a query
    that never ran is judged by nothing, so it is unknown. A pooled signal also reads the
    sampled groups the same hypothesis names for it with the same subject and polarity."""
    if scopes is None or p.query_key is None:
        return None
    keys = {p.query_key}
    if p.signal in POOLED_SIGNALS:
        keys |= {
            q.query_key
            for q in h.predicted_observations
            if q.query_key and (q.signal, q.subject, q.expect) == (p.signal, p.subject, p.expect)
        }
    return frozenset().union(*(scopes.get(k, frozenset()) for k in keys))


def observe(
    h: Hypothesis, p: PredictedObservation, results: list[ToolResult], scopes: Scopes | None
) -> Observation | None:
    """What the signal shows over the results this prediction concerns. None when it has no
    signal."""
    if p.signal is None:
        return None
    covered = covered_queries(h, p, scopes)
    visible = results if covered is None else [r for r in results if r.query_id in covered]
    return evaluate(p.signal, p.subject, visible)


@dataclass(frozen=True)
class PredictionOutcome:
    signal: str
    expect: bool
    observed: bool | None
    detail: str
    restates_trigger: bool = False
    tool: str = ""
    description: str = ""
    subject: str | None = None
    # The executed queries whose results this prediction was judged by.
    query_ids: tuple[str, ...] = ()

    @property
    def state(self) -> Literal["met", "unmet", "unknown"]:
        if self.observed is None:
            return "unknown"
        return "met" if self.observed == self.expect else "unmet"


@dataclass(frozen=True)
class Assessment:
    hypothesis_id: str
    outcomes: tuple[PredictionOutcome, ...]
    # Predictions set aside because their records cannot bear on the hypothesis's subsystem.
    rejected: tuple[str, ...] = ()

    def count(self, state: str) -> int:
        return sum(1 for o in self.outcomes if o.state == state)

    @property
    def shows_own_mechanism(self) -> bool:
        """A prediction that a signal is present was met, and the signal is not the symptom
        the trigger already stated."""
        return any(o.state == "met" and o.expect and not o.restates_trigger for o in self.outcomes)


def _dedupe(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    return list(dict.fromkeys(refs))


def assess(
    plan: list[Hypothesis],
    results: list[ToolResult],
    symptom_signals: frozenset[Signal] = frozenset(),
    scopes: Scopes | None = None,
) -> tuple[list[Hypothesis], dict[str, Assessment]]:
    """The ledger as the results leave it, and each hypothesis's per-prediction outcomes.
    plan holds the hypotheses as proposed, so a statement is never extended twice.
    symptom_signals are the signals the trigger already stated. scopes say which executed
    queries each prediction's query_key covers, and the loop always passes them."""
    updated: list[Hypothesis] = []
    assessments: dict[str, Assessment] = {}
    for h in plan:
        supporting: list[EvidenceRef] = []
        contradicting: list[EvidenceRef] = []
        outcomes: list[PredictionOutcome] = []
        rejected: list[str] = []
        met_notes: list[str] = []
        unmet_notes: list[str] = []
        for p in h.predicted_observations:
            obs = observe(h, p, results, scopes)
            if obs is None or p.signal is None:
                continue
            if p.expect and obs.observed and obs.subsystems and h.subsystem not in obs.subsystems:
                fits = ", ".join(sorted(obs.subsystems))
                rejected.append(
                    f"{p.signal} was observed ({obs.detail}), but those records bear on {fits} "
                    f"and cannot show a fault in {h.subsystem}"
                )
                continue
            covered = covered_queries(h, p, scopes)
            outcome = PredictionOutcome(
                p.signal,
                p.expect,
                obs.observed,
                obs.detail,
                p.signal in symptom_signals,
                p.tool,
                p.description,
                p.subject,
                tuple(
                    sorted(r.query_id for r in results if covered is None or r.query_id in covered)
                ),
            )
            outcomes.append(outcome)
            if outcome.state == "met":
                supporting += list(obs.support if p.expect else obs.against)
                met_notes.append(obs.detail)
            elif outcome.state == "unmet":
                contradicting += list(obs.against if p.expect else obs.support)
                unmet_notes.append(obs.detail)
        supporting, contradicting = _dedupe(supporting), _dedupe(contradicting)
        a = Assessment(h.hypothesis_id, tuple(outcomes), tuple(dict.fromkeys(rejected)))
        assessments[h.hypothesis_id] = a
        # A hypothesis is supported only when it predicted a signal to be present, the signal
        # was seen, and the signal is not just the incident's own symptom. Predictions of
        # absence that held (a rival's signal was missing) clear it of one objection, and the
        # trigger's symptom shows the incident exists. Neither shows a mechanism, so both
        # leave the hypothesis open.
        if a.shows_own_mechanism and not a.count("unmet") and supporting:
            status = "supported"
        elif a.count("unmet") and contradicting:
            # Only a failed prediction of presence refutes: the hypothesis's own mechanism was
            # looked for and is missing. A failed prediction of absence rests on the model's
            # claim that the hypothesis rules a signal out, which weakens it and no more.
            direct = any(o.state == "unmet" and o.expect for o in outcomes)
            status = "refuted" if direct and not a.count("met") else "weakened"
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
    lines = [
        f"{h.hypothesis_id} ({h.subsystem}): {o.signal} could not be told, {o.detail}"
        for o in a.outcomes
        if o.state == "unknown"
    ]
    lines += [f"{h.hypothesis_id} ({h.subsystem}): {why}" for why in a.rejected]
    if h.status == "open" and a.count("met") and not a.shows_own_mechanism:
        lines.append(
            f"{h.hypothesis_id} ({h.subsystem}) is only not contradicted or restates the "
            "incident's own symptom: no record shows its own mechanism"
        )
    return lines


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
        high = any(h.status == "refuted" for h in refuted) and not unverified_empties
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
