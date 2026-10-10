"""
Typed contracts for the Reliability Incident Investigator.

Pure data and validation only. Nothing here calls a model or a tool. The investigator's
reasoning loop does not exist yet (Day 11.1). These models are what that loop reads and
writes, and what the known-answer harness grades.

Two distinctions are enforced by the shape of the data, not by prose:

- InvestigationState is the working record. Evidence is cited by EvidenceRef, and a ref is
  only valid when a query executed in this investigation returned it (see citations.py).
- IncidentReport keeps observation, correlation and causation in separate fields, keeps
  missing evidence apart from evidence against, keeps an unavailable tool apart from an
  empty result, and keeps the one proposed verification apart from the queries actually run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ToolName = Literal[
    "get_failing_traces",
    "explain_guardrail_decision",
    "get_judge_scores",
    "search_prompt_injections",
    "get_drift_report",
    "search_traces",
    "get_trace_detail",
    "list_red_team_executions",
    "get_red_team_execution",
]
TOOL_NAMES: tuple[ToolName, ...] = (
    "get_failing_traces",
    "explain_guardrail_decision",
    "get_judge_scores",
    "search_prompt_injections",
    "get_drift_report",
    "search_traces",
    "get_trace_detail",
    "list_red_team_executions",
    "get_red_team_execution",
)

# ok: the tool returned records. empty: the tool ran and matched nothing. unavailable: the
# tool could not run, so the result says nothing about the platform. rejected: the tool
# refused the arguments (a caller error, never retried).
ToolStatus = Literal["ok", "empty", "unavailable", "rejected"]

Subsystem = Literal[
    "input_rails",
    "retrieval",
    "downstream_model",
    "output_rails",
    "judges",
    "event_pipeline",
]

EvidenceKind = Literal[
    "query_result",
    "trace",
    "guardrail_decision",
    "judge_scores",
    "injection_event",
    "drift_report",
    "red_team_execution",
]

TriggerKind = Literal[
    "faithfulness_block_cluster",
    "judge_disagreement_cluster",
    "red_team_miss",
    "error_kind_surge",
    "drift_degradation",
    "single_trace",
]

# What a prediction is about. Each signal has one deterministic evaluator (signals.py), so a
# hypothesis is confirmed or contradicted by code reading the tool results, never by a model.
Signal = Literal[
    "judge_failures",
    "judge_drift",
    "chunk_contradicted",
    "chunk_shared_by_failures",
    "block_cluster",
    "injection_surge",
    "rail_regression",
    "rail_working",
    "error_cluster",
]

HypothesisStatus = Literal["open", "supported", "weakened", "refuted"]
Confidence = Literal["low", "medium", "high"]
StoppingReason = Literal[
    "sufficient_evidence",
    "justified_abstention",
    "budget_exhausted",
    "critical_evidence_unavailable",
]

ABSTENTION_STATEMENT = (
    "Insufficient evidence to establish a root cause. Continue monitoring and perform "
    "the proposed verification."
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(_Frozen):
    """A pointer to one record a query returned. kind says which tool family, record_id is
    the id that tool returned (an app_trace_id, an execution_id, a query id)."""

    kind: EvidenceKind
    record_id: str = Field(min_length=1)


class IncidentTrigger(_Frozen):
    kind: TriggerKind
    # A trace id for single_trace, an execution id for red_team_miss, else None.
    reference_id: str | None = None
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reference_when_required(self) -> IncidentTrigger:
        if self.kind in ("single_trace", "red_team_miss") and not self.reference_id:
            raise ValueError(f"a {self.kind} trigger needs a reference_id")
        return self


class TimeWindow(_Frozen):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> TimeWindow:
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self

    @property
    def minutes(self) -> int:
        """Whole minutes, rounded up, for the tools that take time_window_minutes."""
        seconds = (self.end - self.start).total_seconds()
        return max(1, -(-int(seconds) // 60))


class AffectedScope(_Frozen):
    endpoint: str | None = None
    ticker: str | None = None
    trace_ids: list[str] = Field(default_factory=list)


class DataGap(_Frozen):
    """Something the investigator is known not to be able to see, stated up front so a
    missing signal is never read as a clean one."""

    source: str = Field(min_length=1)
    kind: Literal["tool_unavailable", "not_persisted", "withheld", "snapshot_only", "ambiguous"]
    detail: str = Field(min_length=1)


class PredictedObservation(_Frozen):
    """What would be seen, and from which tool, if the hypothesis were true. When signal is
    set, code can check it: expect says whether the hypothesis predicts the signal present
    or absent, and subject narrows it (a chunk id, a rail). Without a signal the prediction
    is prose only and is never counted as met or unmet."""

    tool: ToolName
    description: str = Field(min_length=1)
    signal: Signal | None = None
    expect: bool = True
    subject: str | None = None


class Hypothesis(_Mutable):
    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    subsystem: Subsystem
    predicted_observations: list[PredictedObservation] = Field(min_length=1)
    supporting: list[EvidenceRef] = Field(default_factory=list)
    contradicting: list[EvidenceRef] = Field(default_factory=list)
    status: HypothesisStatus = "open"
    # The symptom this hypothesis explains. Hypotheses that share one are rivals, because one
    # symptom has one cause. Hypotheses with different symptoms can all be true.
    symptom: str = Field(default="incident", min_length=1)

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> Hypothesis:
        if self.status == "supported" and not self.supporting:
            raise ValueError("a supported hypothesis needs supporting evidence")
        if self.status in ("weakened", "refuted") and not self.contradicting:
            raise ValueError(f"a {self.status} hypothesis needs contradicting evidence")
        return self


class Budgets(_Frozen):
    """Ceilings for one investigation. These are starting values, not tuned optima."""

    max_tool_calls: int = Field(default=8, ge=0)
    max_inference_calls: int = Field(default=2, ge=0)
    max_hypothesis_rounds: int = Field(default=3, ge=0)
    max_wall_clock_s: float = Field(default=120.0, gt=0)


class BudgetUsage(_Frozen):
    tool_calls: int = 0
    inference_calls: int = 0
    hypothesis_rounds: int = 0
    wall_clock_s: float = 0.0


class ExecutedQuery(_Frozen):
    """One tool call made in this investigation. evidence is what it returned, which is
    the only thing a citation may point at."""

    query_id: str
    tool: ToolName
    args: dict[str, object]
    status: ToolStatus
    evidence: list[EvidenceRef] = Field(default_factory=list)
    error: str | None = None
    retry_justification: str | None = None
    # An empty result from a tool whose failed query reads the same as no rows, on a transport
    # that cannot tell the two apart. It is not a clean "nothing happened".
    empty_unverified: bool = False
    # The hypotheses this query was chosen to tell apart. Empty for the opening query.
    separates: list[str] = Field(default_factory=list)


class InvestigationState(_Mutable):
    incident_id: str = Field(min_length=1)
    trigger: IncidentTrigger
    window: TimeWindow
    scope: AffectedScope = Field(default_factory=AffectedScope)
    known_data_gaps: list[DataGap] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    executed_queries: list[ExecutedQuery] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    status: Literal["running", "stopped"] = "running"
    stopping_reason: StoppingReason | None = None

    @model_validator(mode="after")
    def _stopped_has_a_reason(self) -> InvestigationState:
        if self.status == "stopped" and self.stopping_reason is None:
            raise ValueError("a stopped investigation needs a stopping_reason")
        if self.status == "running" and self.stopping_reason is not None:
            raise ValueError("a running investigation has no stopping_reason")
        return self


class Claim(_Frozen):
    statement: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)


class CausalClaim(_Frozen):
    """A claim that something caused something. basis says what supports it: observational
    means stored records only. controlled_test means a stored Red Team execution that
    exercised the defense on purpose.

    scope says what the claim is about. test_behavior is a claim about the test itself (the
    defense behaves this way under this controlled input). production_incident is a claim
    about what caused the incident. The observational surface cannot establish that, and a
    controlled test shows only how the defense behaves, so v1 never accepts a
    production_incident causal claim. The production cause stays a hypothesis."""

    statement: str = Field(min_length=1)
    basis: Literal["observational", "controlled_test"]
    scope: Literal["test_behavior", "production_incident"] = "production_incident"
    evidence: list[EvidenceRef] = Field(min_length=1)


class EvidenceAgainst(_Frozen):
    hypothesis_id: str
    statement: str = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)


class RankedHypothesis(_Frozen):
    hypothesis_id: str
    rank: int = Field(ge=1)
    subsystem: Subsystem
    statement: str = Field(min_length=1)
    confidence: Confidence
    supporting: list[EvidenceRef] = Field(default_factory=list)
    contradicting: list[EvidenceRef] = Field(default_factory=list)


class ProposedVerification(_Frozen):
    """The single next step the investigator recommends. It is never run here, and
    executed is fixed to False so a report cannot claim otherwise. none_available says that
    every safe read-only step on offer was already executed."""

    kind: Literal["red_team_scenario", "read_only_query", "none_available"]
    scenario_id: str | None = Field(default=None, max_length=16)
    tool: ToolName | None = None
    args: dict[str, object] | None = None
    rationale: str = Field(min_length=1)
    executed: Literal[False] = False

    @model_validator(mode="after")
    def _fields_match_kind(self) -> ProposedVerification:
        if self.kind == "red_team_scenario" and not self.scenario_id:
            raise ValueError("a red_team_scenario verification needs a scenario_id")
        if self.kind == "read_only_query" and (self.tool is None or self.args is None):
            raise ValueError("a read_only_query verification needs a tool and its args")
        if self.kind == "none_available" and (self.scenario_id or self.tool or self.args):
            raise ValueError("a none_available verification names no step")
        return self


class IncidentReport(_Frozen):
    incident_id: str = Field(min_length=1)
    outcome: Literal["diagnosis", "abstention"]
    ranked_hypotheses: list[RankedHypothesis] = Field(default_factory=list)
    # Observation, correlation and causation are separate lists on purpose.
    observations: list[Claim] = Field(default_factory=list)
    correlations: list[Claim] = Field(default_factory=list)
    causal_claims: list[CausalClaim] = Field(default_factory=list)
    # What was not available to establish a conclusion, apart from what cut against one.
    missing_evidence: list[str] = Field(default_factory=list)
    evidence_against: list[EvidenceAgainst] = Field(default_factory=list)
    # A tool that could not run, apart from a query that ran and matched nothing.
    tool_unavailable: list[ToolName] = Field(default_factory=list)
    empty_results: list[str] = Field(default_factory=list)
    # Queries actually executed, apart from the one verification only proposed.
    tests_actually_run: list[str] = Field(default_factory=list)
    proposed_verification: ProposedVerification
    limitations: list[str] = Field(default_factory=list)
    stopping_reason: StoppingReason
    abstention_statement: str | None = None

    @model_validator(mode="after")
    def _outcome_shape(self) -> IncidentReport:
        ranks = sorted(h.rank for h in self.ranked_hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hypothesis ranks must be 1..n with no gaps or repeats")
        if self.outcome == "diagnosis":
            if not self.ranked_hypotheses:
                raise ValueError("a diagnosis needs at least one ranked hypothesis")
            if self.abstention_statement is not None:
                raise ValueError("a diagnosis carries no abstention statement")
        else:
            if self.abstention_statement is None:
                raise ValueError("an abstention needs its abstention statement")
            if self.causal_claims:
                raise ValueError("an abstention makes no causal claim")
            if any(h.confidence != "low" for h in self.ranked_hypotheses):
                raise ValueError("an abstention ranks no hypothesis above low confidence")
        return self


class InvestigationResult(_Frozen):
    """What an investigator returns: the report and the final state it was built from."""

    report: IncidentReport
    state: InvestigationState
