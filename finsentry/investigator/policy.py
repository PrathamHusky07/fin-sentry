"""
Budget accounting and the stopping policy. Pure functions over InvestigationState: each
returns a new state or a verdict and none of them performs I/O.

The ceilings live in contracts.Budgets (8 tool calls, 2 inference calls, 3 hypothesis
rounds, 120 seconds). They are starting values chosen to bound a run, not tuned optima.

An investigator asks admit_* before it acts and calls record_* after. record_query checks
admission again, so the repeat-query rule cannot be bypassed by skipping the first check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from finsentry.investigator.contracts import (
    TOOL_NAMES,
    ExecutedQuery,
    Hypothesis,
    InvestigationState,
    StoppingReason,
    ToolName,
    TriggerKind,
)

# Tools whose evidence an investigation of that trigger cannot reach a conclusion without.
CRITICAL_TOOLS: dict[TriggerKind, tuple[ToolName, ...]] = {
    "faithfulness_block_cluster": ("get_failing_traces",),
    "judge_disagreement_cluster": ("search_traces",),
    "red_team_miss": ("get_red_team_execution",),
    "error_kind_surge": ("get_failing_traces",),
    "drift_degradation": ("get_drift_report",),
    "single_trace": ("get_trace_detail",),
}

# A critical tool counts as unavailable after this many attempts, all unavailable: the first
# call and one justified retry.
UNAVAILABLE_ATTEMPTS = 2


class PolicyViolationError(RuntimeError):
    """An action the policy does not allow was recorded anyway."""


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str = ""


def _replace(state: InvestigationState, **changes: object) -> InvestigationState:
    """A new state with the changes applied and every invariant checked again."""
    return InvestigationState.model_validate({**state.model_dump(), **changes})


def canonical_args(args: dict[str, object]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def next_query_id(state: InvestigationState) -> str:
    return f"q{len(state.executed_queries) + 1}"


def exhausted_ceilings(state: InvestigationState) -> list[str]:
    """Names of the ceilings the run has reached. A ceiling of N is reached after N uses."""
    b, u = state.budgets, state.usage
    reached = {
        "tool_calls": u.tool_calls >= b.max_tool_calls,
        "inference_calls": u.inference_calls >= b.max_inference_calls,
        "hypothesis_rounds": u.hypothesis_rounds >= b.max_hypothesis_rounds,
        "wall_clock": u.wall_clock_s >= b.max_wall_clock_s,
    }
    return [name for name, hit in reached.items() if hit]


def admit_query(
    state: InvestigationState,
    tool: str,
    args: dict[str, object],
    retry_justification: str | None = None,
) -> Admission:
    if state.status == "stopped":
        return Admission(False, "the investigation has already stopped")
    if tool not in TOOL_NAMES:
        return Admission(False, f"{tool} is not one of the nine read-only tools")
    ceilings = [c for c in exhausted_ceilings(state) if c in ("tool_calls", "wall_clock")]
    if ceilings:
        return Admission(False, f"budget exhausted: {', '.join(ceilings)}")
    key = canonical_args(args)
    prior = [q for q in state.executed_queries if q.tool == tool and canonical_args(q.args) == key]
    if not prior:
        return Admission(True)
    last = prior[-1]
    if last.status == "unavailable":
        if retry_justification and retry_justification.strip():
            return Admission(True, f"retry of {last.query_id}, which was unavailable")
        return Admission(False, f"{last.query_id} was unavailable, a retry needs a justification")
    if last.status == "rejected":
        return Admission(False, f"{last.query_id} was rejected, change the arguments")
    return Admission(False, f"identical query already executed as {last.query_id}")


def record_query(
    state: InvestigationState, query: ExecutedQuery, elapsed_s: float
) -> InvestigationState:
    admission = admit_query(state, query.tool, query.args, query.retry_justification)
    if not admission.allowed:
        raise PolicyViolationError(admission.reason)
    usage = state.usage.model_copy(update={"tool_calls": state.usage.tool_calls + 1})
    return _replace(
        state,
        executed_queries=[*state.executed_queries, query],
        usage=usage.model_copy(update={"wall_clock_s": max(usage.wall_clock_s, elapsed_s)}),
    )


def with_elapsed(state: InvestigationState, elapsed_s: float) -> InvestigationState:
    """Set the wall-clock reading. It only moves forward."""
    usage = state.usage.model_copy(
        update={"wall_clock_s": max(state.usage.wall_clock_s, elapsed_s)}
    )
    return _replace(state, usage=usage)


def admit_inference(state: InvestigationState) -> Admission:
    if state.status == "stopped":
        return Admission(False, "the investigation has already stopped")
    if "inference_calls" in exhausted_ceilings(state):
        return Admission(False, "budget exhausted: inference_calls")
    return Admission(True)


def record_inference(state: InvestigationState) -> InvestigationState:
    admission = admit_inference(state)
    if not admission.allowed:
        raise PolicyViolationError(admission.reason)
    usage = state.usage.model_copy(update={"inference_calls": state.usage.inference_calls + 1})
    return _replace(state, usage=usage)


def record_hypothesis_round(
    state: InvestigationState, hypotheses: list[Hypothesis]
) -> InvestigationState:
    """Replace the ledger with the updated hypotheses and count one update round."""
    if state.status == "stopped" or "hypothesis_rounds" in exhausted_ceilings(state):
        raise PolicyViolationError("no hypothesis-update round left")
    rounds = state.usage.hypothesis_rounds + 1
    usage = state.usage.model_copy(update={"hypothesis_rounds": rounds})
    return _replace(state, hypotheses=hypotheses, usage=usage)


def critical_unavailable(state: InvestigationState) -> list[ToolName]:
    """Critical tools attempted UNAVAILABLE_ATTEMPTS times with no attempt that ran."""
    unavailable: list[ToolName] = []
    for tool in CRITICAL_TOOLS[state.trigger.kind]:
        attempts = [q.status for q in state.executed_queries if q.tool == tool]
        ran = any(s in ("ok", "empty") for s in attempts)
        if not ran and attempts.count("unavailable") >= UNAVAILABLE_ATTEMPTS:
            unavailable.append(tool)
    return unavailable


def decide_stop(
    state: InvestigationState, *, evidence_sufficient: bool = False, abstain: bool = False
) -> StoppingReason | None:
    """The stopping rule, in precedence order. Unavailable critical evidence ends the run
    first, because no later step can supply it. Sufficient evidence comes next, then an
    abstention the investigator justified, then an exhausted budget. None means continue."""
    if critical_unavailable(state):
        return "critical_evidence_unavailable"
    if evidence_sufficient:
        return "sufficient_evidence"
    if abstain:
        return "justified_abstention"
    if exhausted_ceilings(state):
        return "budget_exhausted"
    return None


def finish(state: InvestigationState, reason: StoppingReason) -> InvestigationState:
    if state.status == "stopped":
        raise PolicyViolationError("the investigation has already stopped")
    return _replace(state, status="stopped", stopping_reason=reason)
