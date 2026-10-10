"""
Deterministic evaluators for the closed set of signals a prediction can name.

A model proposes hypotheses and says which signal each would show. It never decides whether
the signal was seen. That is decided here, from the tool results the investigation retrieved,
and every evaluator returns the records behind its answer so a citation can point at them.

An Observation reads three ways. observed True means the signal is present and `support`
holds the records that show it. observed False means the signal is absent and `against` holds
the records that show it, when there are any (a healthy drift reading is a record, a query
that matched nothing is not). observed None means the retrieved results cannot tell: the
evidence is partial, ambiguous, or an empty result may have been a failed query.

Thresholds are starting values chosen to bound a judgment, not tuned optima.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from finsentry.events.trace_api import TraceDetailResponse
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import EvidenceRef, Signal, ToolName
from finsentry.mcp.tools.drift import GetDriftReportResult
from finsentry.mcp.tools.injections import SearchPromptInjectionsResult
from finsentry.mcp.tools.judges import GetJudgeScoresResult
from finsentry.mcp.tools.redteam import RedTeamExecutionResult
from finsentry.mcp.tools.traces import GetFailingTracesResult
from finsentry.redteam.records import ExecutionList, ExecutionRecord

CLUSTER_MIN = 5  # traces or events before a pile-up counts as a cluster
JUDGE_FAILURE_MIN = 3
RAIL_SHARE_MIN = 0.6
FLAGGED_SHARE_MIN = 0.8  # of the sampled disagreeing traces
DISAGREEMENT_GAP = 0.5  # the flash and frontier faithfulness gap the platform calls disagreement
REF_CAP = 5

# Which tools can show each signal. A prediction naming another tool is dropped.
SIGNAL_TOOLS: dict[Signal, tuple[ToolName, ...]] = {
    "judge_failures": ("get_failing_traces", "get_judge_scores"),
    "judge_drift": ("get_drift_report",),
    "chunk_contradicted": ("get_trace_detail",),
    "chunk_shared_by_failures": ("get_trace_detail",),
    "block_cluster": ("get_failing_traces",),
    "injection_surge": ("search_prompt_injections", "get_failing_traces"),
    "rail_regression": ("get_red_team_execution", "list_red_team_executions"),
    "rail_working": ("get_red_team_execution", "list_red_team_executions"),
    "error_cluster": ("get_failing_traces",),
}


@dataclass(frozen=True)
class Observation:
    observed: bool | None
    support: tuple[EvidenceRef, ...] = ()
    against: tuple[EvidenceRef, ...] = ()
    detail: str = ""
    subject: str | None = None


UNKNOWN = Observation(None, detail="no retrieved result bears on this signal")


def _ref(kind: str, record_id: str) -> EvidenceRef:
    return EvidenceRef(kind=kind, record_id=record_id)  # type: ignore[arg-type]


def _capped(kind: str, ids: list[str]) -> tuple[EvidenceRef, ...]:
    return tuple(_ref(kind, i) for i in list(dict.fromkeys(ids))[:REF_CAP])


def _ran(results: list[ToolResult], *tools: ToolName) -> list[ToolResult]:
    return [r for r in results if r.tool in tools and r.status in ("ok", "empty")]


def _none_found(results: list[ToolResult]) -> bool | None:
    """True when every result of these tools was a verified empty, None when an empty may
    have been a failed query, False when some result held data."""
    if any(r.status == "ok" for r in results):
        return False
    if any(r.empty_unverified for r in results):
        return None
    return True if results else None


def _failing(results: list[ToolResult]) -> list[GetFailingTracesResult]:
    return [
        r.payload
        for r in _ran(results, "get_failing_traces")
        if isinstance(r.payload, GetFailingTracesResult)
    ]


def judge_failures(results: list[ToolResult], subject: str | None) -> Observation:
    failed = [
        t.app_trace_id
        for p in _failing(results)
        for t in p.traces
        if t.classification == "judge_pipeline_failure"
    ]
    scored = [
        p.app_trace_id
        for r in _ran(results, "get_judge_scores")
        if isinstance(p := r.payload, GetJudgeScoresResult)
        and any(v.status == "failed" for v in p.verdicts)
    ]
    failed = list(dict.fromkeys(failed))
    if len(failed) >= JUDGE_FAILURE_MIN:
        support = (*_capped("trace", failed), *_capped("judge_scores", scored))
        return Observation(
            True, support, detail=f"{len(failed)} traces in the window had a judge pipeline failure"
        )
    queried = _failing(results)
    if queried:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for p in queried for t in p.traces]),
            detail=f"{len(failed)} judge pipeline failures, below {JUDGE_FAILURE_MIN}",
        )
    return UNKNOWN


def judge_drift(results: list[ToolResult], subject: str | None) -> Observation:
    for r in _ran(results, "get_drift_report"):
        if not isinstance(r.payload, GetDriftReportResult) or r.payload.last_health_reading is None:
            continue
        reading, ref = r.payload.last_health_reading, _ref("drift_report", r.payload.judge_id)
        text = f"judge {r.payload.judge_id} drift state {reading.state}, kappa {reading.kappa}"
        if reading.state == "drifted":
            return Observation(True, (ref,), detail=text)
        if reading.state == "healthy":
            return Observation(False, against=(ref,), detail=text)
        return Observation(None, detail=f"{text}, which is neither drifted nor healthy")
    return UNKNOWN


def _details(results: list[ToolResult]) -> list[TraceDetailResponse]:
    return [
        p
        for r in _ran(results, "get_trace_detail")
        if isinstance(p := r.payload, TraceDetailResponse) and p.found
    ]


def _gap(d: TraceDetailResponse) -> float | None:
    flash = d.flash.faithfulness_score if d.flash else None
    frontier = d.frontier.evidence.faithfulness_score if d.frontier.evidence else None
    if flash is None or frontier is None:
        return None
    return abs(flash - frontier)


def chunk_contradicted(results: list[ToolResult], subject: str | None) -> Observation:
    scored = [(d, g) for d in _details(results) if (g := _gap(d)) is not None]
    disagreeing = [d for d, g in scored if g >= DISAGREEMENT_GAP]
    agreeing = [d for d, g in scored if g < DISAGREEMENT_GAP]
    if len(disagreeing) < 2:
        return Observation(
            None, detail=f"{len(disagreeing)} sampled disagreeing traces, 2 are needed"
        )
    flagged: dict[str, list[str]] = {}
    for d in disagreeing:
        evidence = d.frontier.evidence
        for chunk in evidence.cited_chunks_contradicting if evidence else []:
            flagged.setdefault(chunk, []).append(d.app_trace_id)
    if not flagged:
        ids = [d.app_trace_id for d in disagreeing]
        return Observation(
            False,
            against=_capped("trace", ids),
            detail="no sampled disagreeing trace names a contradicting chunk",
        )
    chunk = subject if subject in flagged else max(sorted(flagged), key=lambda c: len(flagged[c]))
    hits = flagged[chunk]
    counter = [d for d in agreeing if chunk in d.retrieved_chunk_ids]
    share = (
        f"cited as contradicting in {len(hits)} of {len(disagreeing)} sampled disagreeing traces"
    )
    if counter:
        return Observation(
            False,
            support=_capped("trace", hits),
            against=_capped("trace", [d.app_trace_id for d in counter]),
            detail=f"chunk {chunk} is {share}, but {len(counter)} sampled traces that "
            "retrieved it show the judges in agreement",
            subject=chunk,
        )
    if len(hits) >= 2 and len(hits) / len(disagreeing) >= FLAGGED_SHARE_MIN:
        return Observation(
            True,
            _capped("trace", hits),
            detail=f"chunk {chunk} is {share}, and no sampled agreeing trace retrieved it",
            subject=chunk,
        )
    return Observation(None, detail=f"chunk {chunk} is only {share}", subject=chunk)


def chunk_shared_by_failures(results: list[ToolResult], subject: str | None) -> Observation:
    sampled = [d for d in _details(results) if d.rag_status in ("blocked", "error")]
    if len(sampled) < 2:
        return Observation(None, detail=f"{len(sampled)} sampled failed traces, 2 are needed")
    shared = [
        c
        for c in sampled[0].retrieved_chunk_ids
        if all(c in d.retrieved_chunk_ids for d in sampled)
    ]
    if subject in shared:
        shared = [subject]
    if not shared:
        return Observation(
            False,
            against=_capped("trace", [d.app_trace_id for d in sampled]),
            detail="the sampled failed traces share no retrieved chunk",
        )
    chunks = ", ".join(shared)
    return Observation(
        True,
        _capped("trace", [d.app_trace_id for d in sampled]),
        detail=f"chunks {chunks} were retrieved by all {len(sampled)} sampled failed traces",
        subject=shared[0],
    )


def block_cluster(results: list[ToolResult], subject: str | None) -> Observation:
    traces = [
        t for p in _failing(results) for t in p.traces if t.classification == "guardrail_blocked"
    ]
    if not _failing(results):
        return UNKNOWN
    if len(traces) < CLUSTER_MIN:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for t in traces]),
            detail=f"{len(traces)} blocked requests, below a cluster of {CLUSTER_MIN}",
        )
    rails = Counter(t.block_rail or "unknown" for t in traces)
    rail, count = rails.most_common(1)[0]
    if count / len(traces) >= RAIL_SHARE_MIN:
        ids = [t.app_trace_id for t in traces if (t.block_rail or "unknown") == rail]
        return Observation(
            True,
            _capped("trace", ids),
            detail=f"{count} of {len(traces)} blocked requests were blocked by the {rail} rail",
            subject=rail,
        )
    return Observation(
        None, detail=f"{len(traces)} blocked requests spread over {len(rails)} rails"
    )


def injection_surge(results: list[ToolResult], subject: str | None) -> Observation:
    searched = _ran(results, "search_prompt_injections")
    events = [
        e.app_trace_id
        for r in searched
        if isinstance(r.payload, SearchPromptInjectionsResult)
        for e in r.payload.direct
    ]
    if len(events) >= CLUSTER_MIN:
        return Observation(
            True,
            _capped("injection_event", events),
            detail=f"{len(events)} direct injection attempts were blocked by an input rail",
        )
    blocked = [
        t for p in _failing(results) for t in p.traces if "injection" in (t.block_rail or "")
    ]
    if len(blocked) >= CLUSTER_MIN:
        return Observation(
            True,
            _capped("trace", [t.app_trace_id for t in blocked]),
            detail=f"{len(blocked)} requests were blocked by an injection rail",
        )
    if events:
        return Observation(
            False,
            against=_capped("injection_event", events),
            detail=f"{len(events)} direct injection attempts, below {CLUSTER_MIN}",
        )
    if not searched:
        return UNKNOWN
    if _none_found(searched):
        return Observation(False, detail="no direct injection attempts were blocked in the window")
    return Observation(None, detail="an empty injection search may have been a failed query")


def _executions(results: list[ToolResult], scenario: str | None = None) -> list[ExecutionRecord]:
    found: list[ExecutionRecord] = []
    for r in _ran(results, "get_red_team_execution", "list_red_team_executions"):
        if isinstance(r.payload, ExecutionList):
            found += r.payload.executions
        elif isinstance(r.payload, RedTeamExecutionResult) and r.payload.execution is not None:
            found.append(r.payload.execution)
    unique = {e.execution_id: e for e in found}.values()
    return [e for e in unique if scenario is None or e.scenario_id == scenario]


def _missed_when_expected_caught(e: ExecutionRecord) -> bool:
    return e.state == "finished" and e.outcome == "missed" and e.expected.outcome == "caught"


def _earlier_run_of(earlier: ExecutionRecord, later: ExecutionRecord) -> bool:
    return (
        earlier.scenario_id == later.scenario_id
        and earlier.started_at is not None
        and later.started_at is not None
        and earlier.started_at < later.started_at
    )


def rail_regression(results: list[ToolResult], subject: str | None) -> Observation:
    """subject, when given, is a Red Team scenario id and only its executions count."""
    executions = _executions(results, subject)
    if not executions:
        return UNKNOWN
    missed = [e for e in executions if _missed_when_expected_caught(e)]
    if missed:
        ids = [e.execution_id for e in missed]
        earlier = [
            e.execution_id
            for e in executions
            if e.outcome == "caught" and any(_earlier_run_of(e, m) for m in missed)
        ]
        names = ", ".join(sorted({f"{m.scenario_id} ({m.target_layer})" for m in missed}))
        note = (
            f", and was caught in {len(earlier)} earlier run" + ("s" if len(earlier) != 1 else "")
            if earlier
            else ""
        )
        return Observation(
            True,
            (*_capped("red_team_execution", ids), *_capped("red_team_execution", earlier)),
            detail=f"Red Team scenario {names} was missed though its expectation is caught{note}",
        )
    held = [e.execution_id for e in executions if e.outcome == "caught" and e.expectation == "met"]
    return Observation(
        False,
        against=_capped("red_team_execution", held),
        detail="no retrieved Red Team execution missed an attack it was expected to catch",
    )


def rail_working(results: list[ToolResult], subject: str | None) -> Observation:
    """subject, when given, is a Red Team scenario id and only its executions count."""
    executions = _executions(results, subject)
    if not executions:
        return UNKNOWN
    held = [e for e in executions if e.outcome == "caught" and e.expectation == "met"]
    missed = [e for e in executions if _missed_when_expected_caught(e)]
    if missed:
        return Observation(
            False,
            against=_capped("red_team_execution", [e.execution_id for e in missed]),
            detail="a retrieved Red Team execution missed an attack it was expected to catch",
        )
    if held:
        names = ", ".join(sorted({e.scenario_id for e in held}))
        return Observation(
            True,
            _capped("red_team_execution", [e.execution_id for e in held]),
            detail=f"Red Team scenario {names} was caught as expected",
        )
    return UNKNOWN


def error_cluster(results: list[ToolResult], subject: str | None) -> Observation:
    traces = [
        t for p in _failing(results) for t in p.traces if t.classification == "rag_system_error"
    ]
    if not _failing(results):
        return UNKNOWN
    if len(traces) < CLUSTER_MIN:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for t in traces]),
            detail=f"{len(traces)} system errors in the window, below {CLUSTER_MIN}",
        )
    kinds = Counter(t.error_kind or "unknown" for t in traces)
    kind, count = kinds.most_common(1)[0]
    if count / len(traces) >= RAIL_SHARE_MIN:
        ids = [t.app_trace_id for t in traces if (t.error_kind or "unknown") == kind]
        return Observation(
            True,
            _capped("trace", ids),
            detail=f"{count} of {len(traces)} system errors share the error kind {kind}",
            subject=kind,
        )
    return Observation(
        None, detail=f"{len(traces)} system errors spread over {len(kinds)} error kinds"
    )


EVALUATORS: dict[Signal, Callable[[list[ToolResult], str | None], Observation]] = {
    "judge_failures": judge_failures,
    "judge_drift": judge_drift,
    "chunk_contradicted": chunk_contradicted,
    "chunk_shared_by_failures": chunk_shared_by_failures,
    "block_cluster": block_cluster,
    "injection_surge": injection_surge,
    "rail_regression": rail_regression,
    "rail_working": rail_working,
    "error_cluster": error_cluster,
}


def evaluate(signal: Signal, subject: str | None, results: list[ToolResult]) -> Observation:
    return EVALUATORS[signal](results, subject)
