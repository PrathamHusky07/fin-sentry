"""
Evidence validation. A report is checked against the state of the investigation that
produced it, never on its own.

A citation is valid only when a query executed in this investigation returned that record.
A plausible trace id, an id from another investigation, or an id the investigator never
retrieved is rejected. A report with any rejected citation is invalid, however well it reads.

The same pass keeps the report honest about the distinctions its fields encode: a tool that
could not run is not reported as an empty result, a verification that was only proposed is
not one that was run, and a causal claim resting on a controlled test cites one.

Three more boundaries close here. A query_result ref says a query ran, so it is provenance
for tests_actually_run and empty_results and never evidence for a claim. A controlled test
can support a claim about the test, never a production cause (an observational causal claim
stays valid and earns no causal credit, as before). And the report must agree with
the investigation's own ledger: every executed query listed once, every empty result listed
once, and the ranking drawn from the ledger's hypotheses and the evidence attached to them.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from pydantic import ValidationError

from finsentry.investigator.contracts import (
    EvidenceRef,
    IncidentReport,
    InvestigationState,
    ProposedVerification,
)
from finsentry.investigator.policy import canonical_args
from finsentry.investigator.reports import unexecuted_candidates
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.redteam.registry import get_scenario


@dataclass(frozen=True)
class ReportValidation:
    valid: bool
    problems: tuple[str, ...]


def retrieved_evidence(state: InvestigationState) -> frozenset[EvidenceRef]:
    """Every record a query in this investigation returned. Unavailable and rejected calls
    return none."""
    return frozenset(ref for q in state.executed_queries for ref in q.evidence)


def record_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """The refs that point at a stored record. A query_result ref points at a query."""
    return [r for r in refs if r.kind != "query_result"]


def cited_refs(report: IncidentReport) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for h in report.ranked_hypotheses:
        refs += [*h.supporting, *h.contradicting]
    for claim in (*report.observations, *report.correlations):
        refs += claim.evidence
    for causal in report.causal_claims:
        refs += causal.evidence
    for against in report.evidence_against:
        refs += against.evidence
    return refs


def verification_problems(v: ProposedVerification, state: InvestigationState) -> list[str]:
    if v.kind == "none_available":
        left = unexecuted_candidates(state)
        if left:
            return [f"proposed verification is none_available, but {left[0].tool} was not executed"]
        return []
    if v.kind == "red_team_scenario":
        if v.scenario_id is None or get_scenario(v.scenario_id) is None:
            return [f"proposed verification names unknown Red Team scenario {v.scenario_id!r}"]
        return []
    if v.tool is None or v.args is None:
        return ["proposed read-only query has no tool or arguments"]
    try:
        inspect.signature(getattr(McpReadTools, v.tool)).bind(None, **v.args)
    except TypeError as exc:
        return [f"proposed read-only query is not a valid call to {v.tool}: {exc}"]
    key = canonical_args(v.args)
    if any(q.tool == v.tool and canonical_args(q.args) == key for q in state.executed_queries):
        return [f"proposed verification {v.tool} was already executed, so it is not a next step"]
    return []


def _duplicates(items: list[str]) -> list[str]:
    return sorted({i for i in items if items.count(i) > 1})


def _material_evidence_problems(report: IncidentReport) -> list[str]:
    """A claim is backed by records. A ref that only says a query ran backs nothing."""
    groups: list[tuple[str, list[EvidenceRef]]] = []
    for h in report.ranked_hypotheses:
        groups.append((f"hypothesis {h.hypothesis_id} support", h.supporting))
        groups.append((f"hypothesis {h.hypothesis_id} contradiction", h.contradicting))
    groups += [("a correlation", c.evidence) for c in report.correlations]
    groups += [("a causal claim", c.evidence) for c in report.causal_claims]
    groups += [("evidence against", a.evidence) for a in report.evidence_against]
    return [
        f"{where} cites {ref.kind}:{ref.record_id}, which shows a query ran and is not a record"
        for where, refs in groups
        for ref in refs
        if ref.kind == "query_result"
    ]


def _causal_problems(report: IncidentReport) -> list[str]:
    problems: list[str] = []
    for causal in report.causal_claims:
        if causal.basis == "controlled_test" and not any(
            r.kind == "red_team_execution" for r in causal.evidence
        ):
            problems.append("a controlled_test causal claim cites no Red Team execution")
        if causal.basis == "controlled_test" and causal.scope == "production_incident":
            problems.append(
                "a controlled test shows how a defense behaves, not what caused the incident, "
                "so a production_incident causal claim cannot rest on one"
            )
        if causal.basis == "observational" and causal.scope == "test_behavior":
            problems.append("an observational claim cannot describe a controlled test")
    return problems


def _ledger_problems(report: IncidentReport, state: InvestigationState) -> list[str]:
    problems: list[str] = []
    ledger = {h.hypothesis_id: h for h in state.hypotheses}
    ranked_ids = [r.hypothesis_id for r in report.ranked_hypotheses]
    problems += [f"ranks hypothesis {i} more than once" for i in _duplicates(ranked_ids)]
    for ranked in report.ranked_hypotheses:
        entry = ledger.get(ranked.hypothesis_id)
        if entry is None:
            problems.append(f"ranks hypothesis {ranked.hypothesis_id}, which is not in the ledger")
            continue
        if ranked.subsystem != entry.subsystem:
            problems.append(
                f"ranks {ranked.hypothesis_id} under subsystem {ranked.subsystem}, "
                f"the ledger has {entry.subsystem}"
            )
        for kind, cited, attached in (
            ("support", ranked.supporting, entry.supporting),
            ("contradiction", ranked.contradicting, entry.contradicting),
        ):
            problems += [
                f"{ranked.hypothesis_id} cites {r.kind}:{r.record_id} as {kind}, "
                "which the ledger did not attach to it"
                for r in cited
                if r not in attached
            ]
    if report.outcome == "diagnosis":
        problems += [
            f"omits ledger hypothesis {i} from the ranking" for i in ledger if i not in ranked_ids
        ]
        top = min(report.ranked_hypotheses, key=lambda h: h.rank)
        if ledger.get(top.hypothesis_id) and ledger[top.hypothesis_id].status == "refuted":
            problems.append(f"top hypothesis {top.hypothesis_id} is refuted in the ledger")
    return problems


def _execution_problems(report: IncidentReport, state: InvestigationState) -> list[str]:
    problems: list[str] = []
    by_id = {q.query_id: q for q in state.executed_queries}
    problems += [
        f"lists {i} in tests_actually_run more than once"
        for i in _duplicates(report.tests_actually_run)
    ]
    problems += [
        f"lists {i} in empty_results more than once" for i in _duplicates(report.empty_results)
    ]
    for query_id in report.tests_actually_run:
        if query_id not in by_id:
            problems.append(f"lists {query_id} as run, but no such query was executed")
    for query_id in by_id:
        if query_id not in report.tests_actually_run:
            problems.append(f"omits {query_id} from tests_actually_run, though it was executed")
    for query_id in report.empty_results:
        if query_id not in by_id or by_id[query_id].status != "empty":
            problems.append(f"lists {query_id} as an empty result, but it was not an empty result")
    for query_id, query in by_id.items():
        if query.status == "empty" and query_id not in report.empty_results:
            problems.append(f"omits {query_id}, an empty result, from empty_results")
    unavailable = {q.tool for q in state.executed_queries if q.status == "unavailable"}
    for tool in report.tool_unavailable:
        if tool not in unavailable:
            problems.append(f"lists {tool} as unavailable, but it ran")
    for tool in sorted(unavailable - set(report.tool_unavailable)):
        problems.append(f"omits {tool}, which was unavailable, from tool_unavailable")
    return problems


def validate_report(report: IncidentReport, state: InvestigationState) -> ReportValidation:
    problems: list[str] = []
    if report.incident_id != state.incident_id:
        problems.append(f"report is for {report.incident_id}, investigation is {state.incident_id}")
    if report.stopping_reason != state.stopping_reason:
        problems.append("report stopping_reason does not match the investigation's")

    retrieved = retrieved_evidence(state)
    seen: set[EvidenceRef] = set()
    for ref in cited_refs(report):
        if ref not in retrieved and ref not in seen:
            problems.append(
                f"cites {ref.kind}:{ref.record_id}, which no query in this investigation returned"
            )
        seen.add(ref)
    problems += _material_evidence_problems(report)

    problems += _ledger_problems(report, state)
    for against in report.evidence_against:
        if against.hypothesis_id not in {h.hypothesis_id for h in state.hypotheses}:
            problems.append(f"evidence against unknown hypothesis {against.hypothesis_id}")
    if report.outcome == "diagnosis":
        top = min(report.ranked_hypotheses, key=lambda h: h.rank)
        if not record_refs(top.supporting):
            problems.append(f"top hypothesis {top.hypothesis_id} cites no supporting evidence")

    problems += _execution_problems(report, state)
    problems += _causal_problems(report)
    problems += verification_problems(report.proposed_verification, state)
    return ReportValidation(valid=not problems, problems=tuple(problems))


def parse_report(raw: object) -> IncidentReport | None:
    """A report from untrusted structured output, or None when it is malformed."""
    try:
        return IncidentReport.model_validate(raw)
    except ValidationError:
        return None
