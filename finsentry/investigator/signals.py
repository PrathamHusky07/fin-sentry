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

A prediction is bound to the subject it names. A named chunk, rail, error kind or judge is
checked on its own and never replaced by whichever one the records show most. An empty result
that may have been a failed query (empty_unverified) is never read as absence.

An observed-present Observation also says which subsystems the records behind it can bear on
(`subsystems`, empty when unrestricted). The ledger uses that to refuse an attribution the
records cannot support. A finding that fits several subsystems fits each of them.

Thresholds are starting values chosen to bound a judgment, not tuned optima.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from finsentry.events.trace_api import TraceDetailResponse
from finsentry.investigator.adapter import ToolResult
from finsentry.investigator.contracts import EvidenceRef, Signal, Subsystem, ToolName
from finsentry.mcp.tools.drift import GetDriftReportResult, TransitionRecordSummary
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

# Signals that compare sampled populations of traces with each other: chunk_contradicted sets the
# disagreeing sample against the agreeing one, and chunk_shared_by_failures reads every failed
# sample at once. A hypothesis that names one of them for several sampled groups, with the same
# subject and polarity, is asking one comparison, so those groups are read together. Every
# other signal is read from the one query its prediction names.
POOLED_SIGNALS: frozenset[Signal] = frozenset({"chunk_contradicted", "chunk_shared_by_failures"})


# The stage each rail belongs to, by the name the rail reports and by the Colang flow name the
# gateway persists as block_rail. tests/investigator/test_evidence_integrity.py checks that every
# rail the Red Team can target is listed here.
RAIL_STAGE: dict[str, Literal["input", "retrieval", "output"]] = {
    "prompt-guard-2": "input",
    "pii-redaction": "input",
    "llama-guard-3": "input",
    "check prompt injection": "input",
    "check pii": "input",
    "check hazard taxonomy": "input",
    "retrieval-rail": "retrieval",
    "schema-enforcement": "output",
    "regulated-phrases": "output",
    "faithfulness": "output",
}
STAGE_SUBSYSTEM: dict[str, Subsystem] = {
    "input": "input_rails",
    "retrieval": "retrieval",
    "output": "output_rails",
}
UNRECORDED = "unknown"


def defense_subsystems(rails: list[str]) -> frozenset[Subsystem]:
    """The subsystems a controlled test of these rails shows the behavior of: the rail's own
    stage, and nothing else. Empty when a rail is not classified."""
    stages = [RAIL_STAGE.get(r) for r in rails]
    if not stages or None in stages:
        return frozenset()
    return frozenset(STAGE_SUBSYSTEM[s] for s in stages if s is not None)


def block_subsystems(rail: str) -> frozenset[Subsystem]:
    """The subsystems a cluster of blocks by this rail can bear on: the rail's own stage, plus
    what feeds it. An output rail trips on what the model wrote, and the faithfulness rail also
    on what the model was given. Empty when the rail is not classified."""
    stage = RAIL_STAGE.get(rail)
    if stage is None:
        return frozenset()
    own: frozenset[Subsystem] = frozenset({STAGE_SUBSYSTEM[stage]})
    if stage != "output":
        return own
    extra: frozenset[Subsystem] = frozenset({"downstream_model"})
    if rail == "faithfulness":
        extra = extra | {"retrieval"}
    return own | extra


@dataclass(frozen=True)
class Observation:
    observed: bool | None
    support: tuple[EvidenceRef, ...] = ()
    against: tuple[EvidenceRef, ...] = ()
    detail: str = ""
    subject: str | None = None
    # Set on a present signal only. The subsystems the records behind it can bear on.
    subsystems: frozenset[Subsystem] = frozenset()


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


def _failing_scoped(
    results: list[ToolResult], *failure_types: str
) -> tuple[list[GetFailingTracesResult], bool]:
    """The failing-traces results that were asked about one of these failure types, and
    whether one such result was an empty that may have been a failed query. A listing of
    another failure type says nothing about this one, and an unverified empty says nothing at
    all, so neither is returned as a result that can show absence."""
    scoped = [
        r
        for r in _ran(results, "get_failing_traces")
        if isinstance(r.payload, GetFailingTracesResult)
        and r.args.get("failure_type", "any") in failure_types
    ]
    usable = [r.payload for r in scoped if not r.empty_unverified]
    return [p for p in usable if isinstance(p, GetFailingTracesResult)], any(
        r.empty_unverified for r in scoped
    )


FAILED_QUERY_NOTE = "an empty failing-traces listing may have been a failed query"


def judge_failures(results: list[ToolResult], subject: str | None) -> Observation:
    listings, unverified = _failing_scoped(results, "judge_failed", "any")
    failed = [
        t.app_trace_id
        for p in listings
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
            True,
            support,
            detail=f"{len(failed)} traces in the window had a judge pipeline failure",
            subsystems=frozenset({"judges", "event_pipeline"}),
        )
    if listings:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for p in listings for t in p.traces]),
            detail=f"{len(failed)} judge pipeline failures, below {JUDGE_FAILURE_MIN}",
        )
    if unverified:
        return Observation(None, detail=FAILED_QUERY_NOTE)
    return UNKNOWN


def _latest(history: list[TransitionRecordSummary]) -> TransitionRecordSummary:
    """The most recent transition: by timestamp when every record has one, else the last."""
    if all(t.observed_at for t in history):
        return max(history, key=lambda t: t.observed_at or "")
    return history[-1]


def _from_history(report: GetDriftReportResult, ref: EvidenceRef) -> Observation:
    """No current reading, so only what the transition log recorded. It is evidence of a past
    change, and the detail says so. It never states a present health state."""
    last = _latest(report.transition_history)
    kappa = f", kappa {last.kappa}" if last.kappa is not None else ""
    base = (
        f"judge {report.judge_id} has no current health reading. Its last recorded transition "
        f"went from {last.previous_state} to {last.new_state} at "
        f"{last.observed_at or 'an unrecorded time'}{kappa}"
    )
    if last.new_state == "drifted":
        return Observation(
            True,
            (ref,),
            detail=f"{base}. That is a record of past drift and no later recovery is recorded, "
            "not a reading of its present state",
            subsystems=frozenset({"judges"}),
        )
    if last.new_state == "healthy":
        return Observation(
            False,
            against=(ref,),
            detail=f"{base}. That is a record of a past recovery, not a reading of the present",
        )
    return Observation(None, detail=f"{base}, which is neither drifted nor healthy")


def judge_drift(results: list[ToolResult], subject: str | None) -> Observation:
    """subject, when given, is a judge id and only that judge's report counts."""
    for r in _ran(results, "get_drift_report"):
        report = r.payload
        if not isinstance(report, GetDriftReportResult):
            continue
        if subject is not None and subject != report.judge_id:
            continue
        ref = _ref("drift_report", report.judge_id)
        reading = report.last_health_reading
        if reading is None:
            if report.transition_history:
                return _from_history(report, ref)
            continue
        text = f"judge {report.judge_id} drift state {reading.state}, kappa {reading.kappa}"
        if reading.state == "drifted":
            return Observation(True, (ref,), detail=text, subsystems=frozenset({"judges"}))
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
    if subject is not None and subject not in flagged:
        others = ", ".join(sorted(flagged))
        return Observation(
            False,
            against=_capped("trace", [d.app_trace_id for d in disagreeing]),
            detail=f"chunk {subject} is not cited as contradicting in any of "
            f"{len(disagreeing)} sampled disagreeing traces, which cite {others}",
            subject=subject,
        )
    chunk = subject or max(sorted(flagged), key=lambda c: len(flagged[c]))
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
            subsystems=frozenset({"retrieval", "judges", "downstream_model"}),
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
    if subject is not None:
        if subject not in shared:
            return Observation(
                False,
                against=_capped("trace", [d.app_trace_id for d in sampled]),
                detail=f"chunk {subject} was not retrieved by all {len(sampled)} sampled "
                "failed traces",
                subject=subject,
            )
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
        subsystems=frozenset({"retrieval", "downstream_model"}),
    )


def _dominant(keys: list[str], subject: str | None) -> tuple[str, str | None]:
    """How a set of traces relates to the key a prediction named, over the key each trace
    records (a rail, an error kind). ("named", key) when the named key, or with no subject the
    most common one, holds at least RAIL_SHARE_MIN of the traces. ("other", key) when a
    recorded key other than the subject does. ("unclear", None) when none does, including when
    the traces do not record the key at all."""
    counts = Counter(keys)
    if subject is not None and counts[subject] / len(keys) >= RAIL_SHARE_MIN:
        return "named", subject
    key, count = counts.most_common(1)[0]
    if count / len(keys) < RAIL_SHARE_MIN:
        return "unclear", None
    if subject is None:
        return "named", key
    return ("unclear", None) if key == UNRECORDED else ("other", key)


def block_cluster(results: list[ToolResult], subject: str | None) -> Observation:
    """subject, when given, is a rail name and only a cluster on that rail supports it."""
    listings, unverified = _failing_scoped(results, "blocked", "any")
    traces = [t for p in listings for t in p.traces if t.classification == "guardrail_blocked"]
    if not listings:
        return Observation(None, detail=FAILED_QUERY_NOTE) if unverified else UNKNOWN
    if len(traces) < CLUSTER_MIN:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for t in traces]),
            detail=f"{len(traces)} blocked requests, below a cluster of {CLUSTER_MIN}",
        )
    rails = [t.block_rail or UNRECORDED for t in traces]
    kind, rail = _dominant(rails, subject)
    if kind == "named" and rail is not None:
        count = rails.count(rail)
        ids = [t.app_trace_id for t in traces if (t.block_rail or UNRECORDED) == rail]
        return Observation(
            True,
            _capped("trace", ids),
            detail=f"{count} of {len(traces)} blocked requests were blocked by the {rail} rail",
            subject=rail,
            subsystems=block_subsystems(rail),
        )
    if kind == "other" and rail is not None:
        ids = [t.app_trace_id for t in traces if (t.block_rail or UNRECORDED) == rail]
        return Observation(
            False,
            against=_capped("trace", ids),
            detail=f"{rails.count(rail)} of {len(traces)} blocked requests were blocked by the "
            f"{rail} rail, not {subject}",
            subject=subject,
        )
    return Observation(
        None, detail=f"{len(traces)} blocked requests spread over {len(set(rails))} rails"
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
            subsystems=frozenset({"input_rails"}),
        )
    blocked = [
        t for p in _failing(results) for t in p.traces if "injection" in (t.block_rail or "")
    ]
    if len(blocked) >= CLUSTER_MIN:
        return Observation(
            True,
            _capped("trace", [t.app_trace_id for t in blocked]),
            detail=f"{len(blocked)} requests were blocked by an injection rail",
            subsystems=frozenset({"input_rails"}),
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
            subsystems=defense_subsystems([m.target_layer for m in missed]),
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
            subsystems=defense_subsystems([e.target_layer for e in held]),
        )
    return UNKNOWN


def error_cluster(results: list[ToolResult], subject: str | None) -> Observation:
    """subject, when given, is an error kind and only a cluster of that kind supports it."""
    listings, unverified = _failing_scoped(results, "error", "any")
    traces = [t for p in listings for t in p.traces if t.classification == "rag_system_error"]
    if not listings:
        return Observation(None, detail=FAILED_QUERY_NOTE) if unverified else UNKNOWN
    if len(traces) < CLUSTER_MIN:
        return Observation(
            False,
            against=_capped("trace", [t.app_trace_id for t in traces]),
            detail=f"{len(traces)} system errors in the window, below {CLUSTER_MIN}",
        )
    kinds = [t.error_kind or UNRECORDED for t in traces]
    kind, name = _dominant(kinds, subject)
    if kind == "named" and name is not None:
        ids = [t.app_trace_id for t in traces if (t.error_kind or UNRECORDED) == name]
        return Observation(
            True,
            _capped("trace", ids),
            detail=f"{kinds.count(name)} of {len(traces)} system errors share the error kind "
            f"{name}",
            subject=name,
        )
    if kind == "other" and name is not None:
        ids = [t.app_trace_id for t in traces if (t.error_kind or UNRECORDED) == name]
        return Observation(
            False,
            against=_capped("trace", ids),
            detail=f"{kinds.count(name)} of {len(traces)} system errors share the error kind "
            f"{name}, not {subject}",
            subject=subject,
        )
    return Observation(
        None, detail=f"{len(traces)} system errors spread over {len(set(kinds))} error kinds"
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
