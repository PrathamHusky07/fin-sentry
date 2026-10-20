"""
What a planner is shown: a compact, deterministic summary of the incident and of what each
executed query returned, plus the instructions for the model.

The digest holds counts, rails, tickers and a few ids, never raw payloads. It is built only
from the trigger, scope, window and tool results. Nothing about a case's seeded cause can
reach it.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from finsentry.events.trace_api import TraceDetailResponse, TraceListResponse
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import Hypothesis, InvestigationState, Signal
from finsentry.investigator.signals import SIGNAL_TOOLS
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import GetFailingTracesResult, GuardrailDecisionSnapshot
from finsentry.redteam.records import ExecutionList, ExecutionRecord
from finsentry.redteam.registry import load_scenarios

ID_LIMIT = 8

SYSTEM_PROMPT = """\
You help investigate one incident on an LLM reliability platform. You propose competing
hypotheses and the read-only queries that would tell them apart. You do not decide anything.
Code runs your queries, checks every prediction against the results and cites only records it
retrieved.

Return JSON for the schema you are given. Rules:
- Give 2 to 4 hypotheses (ids h1 to h4). At least two must compete to explain the same
  symptom, so one query can separate them. Give each a short symptom label. Hypotheses that
  explain different symptoms may all be true and share nothing.
- subsystem is one of input_rails, retrieval, downstream_model, output_rails, judges,
  event_pipeline. Statements are one plain sentence about a possible cause, never a claim of
  proof. Do not use em-dashes.
- Every prediction names a signal, the tool that shows it, the arguments for that tool and
  expect: true when the hypothesis predicts the signal present, false when it predicts it
  absent. Predict what would make a rival wrong, not only what would make you right.
- Choose queries whose results differ between your hypotheses. A query is dropped unless at
  least two hypotheses make a prediction about it and those predictions differ. A query only
  one hypothesis names is dropped, and so is one every hypothesis predicts the same way. Give
  a rival an explicit prediction (expect true or false) about each query that matters.
- To read details of traces an earlier query listed, use get_trace_detail, leave
  app_trace_id out of args_json and set sample_from to that query id. The investigator picks
  traces spread across the list. Never invent a trace id or a chunk id.
- A prediction can name a subject: a Red Team scenario id for rail_regression and
  rail_working, a chunk id for chunk_contradicted. Set it whenever your statement is about
  one scenario or one chunk, because without it the signal reads every retrieved record.
- Code checks a prediction only against the results of the query it names, never against
  another query's results, so name the query that can show the signal.
- Your statement may say only what your predictions can check. Do not claim a wider failure
  or a cause your predictions never test.
- A query already listed in executed_queries has run. Naming it again in a prediction is
  free, and the results already in hand are read for it.
- Use only the tools and signals below. Arguments are JSON text, for example
  {"disagreement": true, "ticker": "AMZN"}.
- Spend few queries. The run has a hard limit on tool calls and on model calls.
- Optionally give one verification: a Red Team scenario id from the list, or one read-only
  query not yet run. It is never executed.
"""

SIGNAL_HELP: dict[Signal, str] = {
    "judge_failures": "at least 3 traces in the window had a judge pipeline failure",
    "judge_drift": "the frontier judge's last persisted reading is drifted (true) or "
    "healthy (false)",
    "chunk_contradicted": "one retrieved chunk is cited as contradicting the answer in most "
    "sampled disagreeing traces and in no sampled agreeing trace",
    "chunk_shared_by_failures": "sampled blocked or errored traces all retrieved the same chunk",
    "block_cluster": "at least 5 blocked requests, most blocked by one rail",
    "injection_surge": "at least 5 direct injection attempts were blocked by an input rail",
    "rail_regression": "a Red Team scenario was missed that its stored expectation says is caught",
    "rail_working": "a Red Team scenario was caught as its stored expectation says",
    "error_cluster": "at least 5 system errors, most with one error kind",
}

TOOL_HELP: dict[str, str] = {
    "get_failing_traces": "args time_window_minutes, failure_type "
    "(blocked|error|judge_failed|any), endpoint, limit. Failing traces with counts.",
    "get_trace_detail": "args app_trace_id. One trace: chunks, both judge tiers' scores, "
    "block rail.",
    "search_traces": "args ticker, disagreement (true: flash and frontier differ by 0.5 or "
    "more), rag_status, judge_state, limit. Lists traces.",
    "get_judge_scores": "args app_trace_id. Judge verdicts for one trace.",
    "explain_guardrail_decision": "args app_trace_id. Which rail decided one trace.",
    "search_prompt_injections": "args time_window_minutes, limit. Direct injection blocks.",
    "get_drift_report": "no args. The frontier judge's last persisted drift reading.",
    "list_red_team_executions": "args category, outcome, scenario_id, limit. Stored Red Team "
    "results.",
    "get_red_team_execution": "args execution_id. One stored Red Team result.",
}


def _top(counter: Counter[str], n: int = 3) -> dict[str, int]:
    return dict(counter.most_common(n))


def _execution(e: ExecutionRecord) -> dict[str, Any]:
    return {
        "execution_id": e.execution_id,
        "scenario": e.scenario_id,
        "outcome": e.outcome,
        "expected": e.expected.outcome,
        "expectation": e.expectation,
    }


def summarize(r: ToolResult) -> dict[str, Any]:
    """The facts a planner may use from one result."""
    p = r.payload
    if isinstance(p, GetFailingTracesResult):
        t = p.traces
        return {
            "classification_counts": p.classification_counts,
            "block_rails": _top(Counter(x.block_rail or "none" for x in t if x.block_rail)),
            "tickers": _top(Counter(x.ticker or "none" for x in t)),
            "error_kinds": _top(Counter(x.error_kind or "none" for x in t if x.error_kind)),
        }
    if isinstance(p, TraceListResponse):
        return {
            "returned": len(p.traces),
            "more_pages": p.next_offset is not None,
            "tickers": _top(Counter(x.ticker or "none" for x in p.traces)),
            "judge_states": _top(Counter(x.judge_state for x in p.traces)),
            "first_ids": [x.app_trace_id for x in p.traces[:ID_LIMIT]],
        }
    if isinstance(p, TraceDetailResponse):
        ev = p.frontier.evidence
        return {
            "found": p.found,
            "rag_status": p.rag_status,
            "block_rail": p.block_rail,
            "judge_state": p.judge_state,
            "chunks": p.retrieved_chunk_ids,
            "flash_faithfulness": p.flash.faithfulness_score if p.flash else None,
            "frontier_faithfulness": ev.faithfulness_score if ev else None,
            "frontier_contradicting_chunks": ev.cited_chunks_contradicting if ev else [],
        }
    if isinstance(p, GetJudgeScoresResult):
        return {"verdicts": [v.status for v in p.verdicts]}
    if isinstance(p, GuardrailDecisionSnapshot):
        return {"found": p.found, "status": p.status, "block_rail": p.block_rail}
    if isinstance(p, SearchPromptInjectionsResult):
        return {"direct": len(p.direct), "by_rail": p.direct_count_by_rail}
    if isinstance(p, GetDriftReportResult):
        rd = p.last_health_reading
        return {
            "judge_id": p.judge_id,
            "state": rd.state if rd else None,
            "kappa": rd.kappa if rd else None,
            "entry_threshold": p.policy.drift_entry_threshold,
            "recovery_threshold": p.policy.recovery_threshold,
            "transitions": len(p.transition_history),
        }
    if isinstance(p, ExecutionList):
        return {"executions": [_execution(e) for e in p.executions[:ID_LIMIT]]}
    if isinstance(p, RedTeamExecutionResult):
        return {"found": p.found, "execution": _execution(p.execution) if p.execution else None}
    return {}


def build_digest(
    state: InvestigationState, results: list[ToolResult], ledger: list[Hypothesis] | None = None
) -> str:
    """The user message for a planner call."""
    by_id = {q.query_id: q for q in state.executed_queries}
    executed = []
    for r in results:
        q = by_id[r.query_id]
        executed.append(
            {
                "query_id": r.query_id,
                "tool": r.tool,
                "args": r.args,
                "status": r.status,
                "empty_may_be_a_failed_query": r.empty_unverified,
                "error": r.error,
                "facts": summarize(r) if r.status in ("ok", "empty") else {},
                "separates": q.separates,
            }
        )
    left = {
        "tool_calls": state.budgets.max_tool_calls - state.usage.tool_calls,
        "model_calls": state.budgets.max_inference_calls - state.usage.inference_calls,
    }
    body: dict[str, Any] = {
        "incident": {
            "trigger": state.trigger.kind,
            "description": state.trigger.description,
            "reference_id": state.trigger.reference_id,
            "window_minutes": state.window.minutes,
            "scope": state.scope.model_dump(exclude_none=True),
        },
        "known_data_gaps": [f"{g.source}: {g.detail}" for g in state.known_data_gaps],
        "executed_queries": executed,
        "budget_left": left,
        "tools": TOOL_HELP,
        "signals": {
            s: {"tools": list(SIGNAL_TOOLS[s]), "meaning": SIGNAL_HELP[s]} for s in SIGNAL_HELP
        },
        "red_team_scenarios": {s.id: s.title for s in load_scenarios()},
    }
    if ledger:
        body["current_hypotheses"] = [
            {
                "id": h.hypothesis_id,
                "symptom": h.symptom,
                "subsystem": h.subsystem,
                "statement": h.statement,
                "status": h.status,
                "supporting": len(h.supporting),
                "contradicting": len(h.contradicting),
            }
            for h in ledger
        ]
    return json.dumps(body, indent=1, default=str)
