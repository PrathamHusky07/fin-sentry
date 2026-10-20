"""
The contract between the investigator and whatever proposes hypotheses.

A planner returns a Plan: two to four competing hypotheses, each with predictions that name a
signal (signals.py), the tool that would show it, and the arguments to call it with. That is
all a model is asked for. Everything it proposes is untrusted. validate_plan drops what the
tool surface does not support and keeps only queries that tell hypotheses apart, so a plan
cannot widen what the investigator may read or turn the run into a sweep.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from finsentry.investigator.contracts import (
    Hypothesis,
    InvestigationState,
    PredictedObservation,
    ProposedVerification,
    Signal,
    Subsystem,
    ToolName,
)
from finsentry.investigator.policy import canonical_args
from finsentry.investigator.signals import SIGNAL_TOOLS
from finsentry.investigator.tool_args import validate_tool_args

# Tools whose single argument is a trace id that a sample can fill in.
SAMPLEABLE_TOOLS: tuple[ToolName, ...] = (
    "get_trace_detail",
    "get_judge_scores",
    "explain_guardrail_decision",
)
MAX_SAMPLE = 3


class PlanningError(RuntimeError):
    """The planner produced nothing the investigator can use."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


LISTING_TOOLS: tuple[ToolName, ...] = ("search_traces", "get_failing_traces")


class QuerySpec(_Model):
    tool: ToolName
    # JSON text, so the schema a model is shown has no free-form object in it.
    args_json: str = "{}"
    # Traces to read, taken from a listing and spread across it, filling app_trace_id. The
    # listing is either an earlier query (sample_from) or one to run first (listing_*).
    sample_from: str | None = None
    listing_tool: ToolName | None = None
    listing_args_json: str = "{}"
    # Only sample traces of this classification (guardrail_blocked, rag_system_error,
    # judge_pipeline_failure) when the listing is a failing-traces result.
    sample_class: str | None = Field(default=None, max_length=40)
    sample_size: int = Field(default=2, ge=1, le=MAX_SAMPLE)


class PlanPrediction(_Model):
    query: QuerySpec
    signal: Signal
    expect: bool = True
    subject: str | None = None
    description: str = Field(min_length=1, max_length=200)


class PlanHypothesis(_Model):
    hypothesis_id: str = Field(pattern=r"^h[1-4]$")
    symptom: str = Field(min_length=1, max_length=40)
    subsystem: Subsystem
    statement: str = Field(min_length=1, max_length=240)
    predictions: list[PlanPrediction] = Field(min_length=1, max_length=4)


class VerificationDraft(_Model):
    kind: Literal["red_team_scenario", "read_only_query"]
    scenario_id: str | None = None
    tool: ToolName | None = None
    args_json: str = "{}"
    rationale: str = Field(min_length=1, max_length=240)


class Plan(_Model):
    hypotheses: list[PlanHypothesis] = Field(min_length=2, max_length=4)
    verification: VerificationDraft | None = None


class Planner(Protocol):
    """Proposes hypotheses and the queries that would separate them. cost_usd is what this
    planner has spent so far, zero for one that calls no model."""

    name: str

    @property
    def cost_usd(self) -> float: ...

    async def plan(self, digest: str, *, round_no: int) -> Plan: ...


@dataclass(frozen=True)
class PlannedQuery:
    tool: ToolName
    args: dict[str, object]
    sample_from: str | None
    sample_size: int
    separates: list[str]
    listing: tuple[ToolName, dict[str, object]] | None = None
    sample_class: str | None = None
    key: str = ""


@dataclass
class ValidatedPlan:
    hypotheses: list[Hypothesis]
    queries: list[PlannedQuery]
    verification: ProposedVerification | None
    notes: list[str] = field(default_factory=list)


def _json_object(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _args(spec: QuerySpec) -> dict[str, object] | None:
    return _json_object(spec.args_json)


def query_key(
    tool: str,
    args: dict[str, object],
    *,
    sample_from: str | None = None,
    sample_size: int = 0,
    sample_class: str | None = None,
    listing: tuple[str, dict[str, object]] | None = None,
) -> str:
    """The name of the query a prediction concerns. A plain query is its tool and arguments, so
    the same call already made (the opening query) is the same query. A sampled query is the
    group of traces taken from one listing, so two samples of the same tool are two groups."""
    base = f"{tool}|{canonical_args(args)}"
    if sample_from is None and listing is None:
        return base
    source = f"{listing[0]}|{canonical_args(listing[1])}" if listing else sample_from
    return f"{base}|sample:{source}|{sample_size}|{sample_class}"


def _spec_key(spec: QuerySpec) -> str:
    return query_key(
        spec.tool,
        _args(spec) or {},
        sample_from=spec.sample_from,
        sample_size=spec.sample_size,
        sample_class=spec.sample_class,
        listing=listing_of(spec),
    )


def listing_of(spec: QuerySpec) -> tuple[ToolName, dict[str, object]] | None:
    if spec.listing_tool is None:
        return None
    return spec.listing_tool, _json_object(spec.listing_args_json) or {}


def _query_problem(spec: QuerySpec, state: InvestigationState) -> str | None:
    """Why this query cannot be run, or None."""
    args = _args(spec)
    if args is None:
        return "arguments are not a JSON object"
    sampled = spec.sample_from is not None or spec.listing_tool is not None
    key = canonical_args(args)
    if not sampled and any(
        q.tool == spec.tool and canonical_args(q.args) == key and q.status in ("ok", "empty")
        for q in state.executed_queries
    ):
        return None  # already answered, so naming it again asks for nothing new
    if not sampled:
        problems = validate_tool_args(spec.tool, args)
        return "; ".join(problems) if problems else None
    if spec.tool not in SAMPLEABLE_TOOLS:
        return f"{spec.tool} cannot be sampled from a listing"
    if "app_trace_id" in args:
        return "a sampled query leaves app_trace_id out"
    if spec.sample_from is not None and spec.listing_tool is not None:
        return "a sampled query names one listing, not two"
    if spec.listing_tool is not None:
        listing = listing_of(spec)
        if spec.listing_tool not in LISTING_TOOLS or listing is None:
            return f"{spec.listing_tool} cannot list traces"
        problems = validate_tool_args(*listing)
        return f"listing {'; '.join(problems)}" if problems else None
    source = next((q for q in state.executed_queries if q.query_id == spec.sample_from), None)
    if source is None or source.status != "ok":
        return f"{spec.sample_from} is not an executed query that returned records"
    if not any(r.kind == "trace" for r in source.evidence):
        return f"{spec.sample_from} returned no traces to sample"
    return None


def _verification(draft: VerificationDraft | None) -> ProposedVerification | None:
    if draft is None:
        return None
    try:
        args = json.loads(draft.args_json or "{}")
        return ProposedVerification(
            kind=draft.kind,
            scenario_id=draft.scenario_id,
            tool=draft.tool,
            args=args if draft.kind == "read_only_query" else None,
            rationale=draft.rationale,
        )
    except (ValueError, TypeError):
        return None


def _separated(
    row: dict[str, frozenset[tuple[str, str | None, bool]]], ids: list[str]
) -> list[str]:
    """The hypotheses this query tells apart: those with an explicit prediction for it that
    differs from another hypothesis's explicit prediction. A hypothesis with no prediction for
    the query is untested by it and is neither compared nor counted as predicting the
    opposite."""
    named = [i for i in ids if i in row]
    return sorted({i for i in named for j in named if i != j and row[i] != row[j]})


def validate_plan(plan: Plan, state: InvestigationState) -> ValidatedPlan:
    """Keep the hypotheses and predictions the tool surface supports and the queries that
    separate hypotheses. Raises PlanningError when fewer than two hypotheses survive."""
    notes: list[str] = []
    kept: list[tuple[PlanHypothesis, list[PlanPrediction]]] = []
    seen_ids: set[str] = set()
    for h in plan.hypotheses:
        if h.hypothesis_id in seen_ids:
            notes.append(f"dropped a repeated hypothesis id {h.hypothesis_id}")
            continue
        seen_ids.add(h.hypothesis_id)
        good: list[PlanPrediction] = []
        for p in h.predictions:
            problem = None
            if p.query.tool not in SIGNAL_TOOLS[p.signal]:
                problem = f"{p.query.tool} cannot show {p.signal}"
            else:
                problem = _query_problem(p.query, state)
            if problem:
                notes.append(f"{h.hypothesis_id}: dropped a {p.signal} prediction, {problem}")
            else:
                good.append(p)
        if good:
            kept.append((h, good))
        else:
            notes.append(f"{h.hypothesis_id}: dropped, no usable prediction")
    if len(kept) < 2:
        raise PlanningError(f"fewer than two usable hypotheses: {'; '.join(notes)}")

    hypotheses = [
        Hypothesis(
            hypothesis_id=h.hypothesis_id,
            statement=h.statement,
            subsystem=h.subsystem,
            symptom=h.symptom,
            predicted_observations=[
                PredictedObservation(
                    tool=p.query.tool,
                    description=p.description,
                    signal=p.signal,
                    expect=p.expect,
                    subject=p.subject,
                    query_key=_spec_key(p.query),
                )
                for p in preds
            ],
        )
        for h, preds in kept
    ]

    by_query: dict[str, dict[str, frozenset[tuple[str, str | None, bool]]]] = {}
    specs: dict[str, QuerySpec] = {}
    for h, preds in kept:
        for p in preds:
            q = p.query
            key = _spec_key(q)
            specs[key] = p.query
            row = by_query.setdefault(key, {})
            row[h.hypothesis_id] = row.get(h.hypothesis_id, frozenset()) | {
                (p.signal, p.subject, p.expect)
            }

    ids = [h.hypothesis_id for h, _ in kept]
    ranked: list[tuple[int, int, str]] = []
    for order, (key, row) in enumerate(by_query.items()):
        apart = _separated(row, ids)
        if not apart:
            tool = specs[key].tool
            named = [i for i in ids if i in row]
            notes.append(
                f"dropped {tool}, only {', '.join(named)} predicts anything from it"
                if len(named) < 2
                else f"dropped {tool}, every hypothesis that predicts from it predicts the same"
            )
            continue
        ranked.append((-len(apart), order, key))
    queries: list[PlannedQuery] = []
    for _, _, key in sorted(ranked):
        spec = specs[key]
        queries.append(
            PlannedQuery(
                spec.tool,
                _args(spec) or {},
                spec.sample_from,
                spec.sample_size,
                _separated(by_query[key], ids),
                listing_of(spec),
                spec.sample_class,
                key,
            )
        )
    return ValidatedPlan(hypotheses, queries, _verification(plan.verification), notes)
