"""
Report builders that need no reasoning: the abstention report, and the default next step
for each trigger.

An abstention is a successful outcome. It says the evidence does not support a root cause,
lists what was and was not available, and still proposes exactly one verification.
"""

from __future__ import annotations

from finsentry.investigator.contracts import (
    ABSTENTION_STATEMENT,
    IncidentReport,
    InvestigationState,
    ProposedVerification,
    ToolName,
)
from finsentry.investigator.policy import canonical_args


def _candidates(state: InvestigationState) -> list[ProposedVerification]:
    minutes = state.window.minutes

    def query(tool: ToolName, rationale: str, **args: object) -> ProposedVerification:
        return ProposedVerification(
            kind="read_only_query", tool=tool, args=dict(args), rationale=rationale
        )

    by_trigger: dict[str, list[ProposedVerification]] = {
        "faithfulness_block_cluster": [
            query(
                "get_failing_traces",
                "List the blocked requests in the window to see whether they share a ticker, "
                "a chunk or a rail.",
                time_window_minutes=minutes,
                failure_type="blocked",
                limit=50,
            ),
        ],
        "judge_disagreement_cluster": [
            query(
                "search_traces",
                "List the traces where the flash and frontier judges disagree by 0.5 or more.",
                disagreement=True,
                limit=20,
            ),
        ],
        "red_team_miss": [
            query(
                "get_red_team_execution",
                "Read the full stored evidence of the missed execution.",
                execution_id=state.trigger.reference_id or "",
            ),
        ],
        "error_kind_surge": [
            query(
                "get_failing_traces",
                "List the errored requests in the window and read their error kinds.",
                time_window_minutes=minutes,
                failure_type="error",
                limit=50,
            ),
        ],
        "drift_degradation": [
            query(
                "get_drift_report",
                "Read the last persisted canary reading and its transition history.",
            ),
        ],
        "single_trace": [
            query(
                "get_trace_detail",
                "Read what is persisted for the trace.",
                app_trace_id=state.trigger.reference_id or "",
            ),
        ],
    }
    fallback = query(
        "list_red_team_executions",
        "Check whether any Red Team execution was missed recently.",
        outcome="missed",
        limit=20,
    )
    return [*by_trigger[state.trigger.kind], fallback]


def unexecuted_candidates(state: InvestigationState) -> list[ProposedVerification]:
    """The candidate next steps this investigation has not already executed, in order."""
    executed = {(q.tool, canonical_args(q.args)) for q in state.executed_queries}
    return [c for c in _candidates(state) if (c.tool, canonical_args(c.args or {})) not in executed]


def default_verification(state: InvestigationState) -> ProposedVerification:
    """The first candidate next step not already executed, always a read-only query so that
    proposing it never starts a run. When every candidate was executed, an explicit
    none_available, because a step the validator rejects is not a next step."""
    remaining = unexecuted_candidates(state)
    if remaining:
        return remaining[0]
    return ProposedVerification(
        kind="none_available",
        rationale="Every safe read-only step on offer was already executed in this "
        "investigation, so no further verification is proposed.",
    )


def abstention_report(
    state: InvestigationState, verification: ProposedVerification | None = None
) -> IncidentReport:
    if state.stopping_reason is None:
        raise ValueError("an abstention report needs a stopped investigation")
    queries = state.executed_queries
    return IncidentReport(
        incident_id=state.incident_id,
        outcome="abstention",
        missing_evidence=list(state.unresolved_questions),
        tool_unavailable=sorted({q.tool for q in queries if q.status == "unavailable"}),
        empty_results=[q.query_id for q in queries if q.status == "empty"],
        tests_actually_run=[q.query_id for q in queries],
        proposed_verification=verification or default_verification(state),
        limitations=[f"{g.source}: {g.detail}" for g in state.known_data_gaps],
        stopping_reason=state.stopping_reason,
        abstention_statement=ABSTENTION_STATEMENT,
    )
