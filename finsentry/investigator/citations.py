"""
Evidence validation. A report is checked against the state of the investigation that
produced it, never on its own.

A citation is valid only when a query executed in this investigation returned that record.
A plausible trace id, an id from another investigation, or an id the investigator never
retrieved is rejected. A report with any rejected citation is invalid, however well it reads.

The same pass keeps the report honest about the distinctions its fields encode: a tool that
could not run is not reported as an empty result, a verification that was only proposed is
not one that was run, and a causal claim resting on a controlled test cites one.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from pydantic import ValidationError

from finsentry.investigator.contracts import (
    EvidenceRef,
    IncidentReport,
    InvestigationState,
)
from finsentry.investigator.policy import canonical_args
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


def _verification_problems(report: IncidentReport, state: InvestigationState) -> list[str]:
    v = report.proposed_verification
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

    ledger = {h.hypothesis_id for h in state.hypotheses}
    for ranked in report.ranked_hypotheses:
        if ranked.hypothesis_id not in ledger:
            problems.append(f"ranks hypothesis {ranked.hypothesis_id}, which is not in the ledger")
    for against in report.evidence_against:
        if against.hypothesis_id not in ledger:
            problems.append(f"evidence against unknown hypothesis {against.hypothesis_id}")
    if report.outcome == "diagnosis":
        top = min(report.ranked_hypotheses, key=lambda h: h.rank)
        if not top.supporting:
            problems.append(f"top hypothesis {top.hypothesis_id} cites no supporting evidence")

    by_id = {q.query_id: q for q in state.executed_queries}
    for query_id in report.tests_actually_run:
        if query_id not in by_id:
            problems.append(f"lists {query_id} as run, but no such query was executed")
    for query_id in report.empty_results:
        if query_id not in by_id or by_id[query_id].status != "empty":
            problems.append(f"lists {query_id} as an empty result, but it was not an empty result")
    unavailable = {q.tool for q in state.executed_queries if q.status == "unavailable"}
    for tool in report.tool_unavailable:
        if tool not in unavailable:
            problems.append(f"lists {tool} as unavailable, but it ran")
    for tool in sorted(unavailable - set(report.tool_unavailable)):
        problems.append(f"omits {tool}, which was unavailable, from tool_unavailable")

    for causal in report.causal_claims:
        if causal.basis == "controlled_test" and not any(
            r.kind == "red_team_execution" for r in causal.evidence
        ):
            problems.append("a controlled_test causal claim cites no Red Team execution")

    problems += _verification_problems(report, state)
    return ReportValidation(valid=not problems, problems=tuple(problems))


def parse_report(raw: object) -> IncidentReport | None:
    """A report from untrusted structured output, or None when it is malformed."""
    try:
        return IncidentReport.model_validate(raw)
    except ValidationError:
        return None
