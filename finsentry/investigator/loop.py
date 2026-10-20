"""
The bounded investigation loop, the interface the eval harness runs, and the way an
investigation starts.

BoundedInvestigator is deterministic code with a model on one narrow job. Code opens the
investigation from the trigger, validates and runs queries, matches evidence to predictions,
keeps the ledger, challenges the leading hypothesis and builds the report. The planner only
proposes hypotheses and the queries that would tell them apart (planning.py), at most twice.
It never sees a case's hidden cause, only the trigger, scope, window and tool results.

Every tool call and model call runs under asyncio.wait_for with the time the wall-clock
budget has left, so a hung call is cancelled and recorded, not waited on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from finsentry.investigator.adapter import KNOWN_TOOL_GAPS, ReadOnlyAdapter, ToolResult
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import (
    AffectedScope,
    Budgets,
    DataGap,
    ExecutedQuery,
    Hypothesis,
    IncidentTrigger,
    InvestigationResult,
    InvestigationState,
    ProposedVerification,
    TimeWindow,
    ToolName,
    TriggerKind,
)
from finsentry.investigator.digest import build_digest
from finsentry.investigator.finalize import build_diagnosis, choose_verification
from finsentry.investigator.ledger import (
    SYMPTOM_SIGNALS,
    Assessment,
    Review,
    Scopes,
    assess,
    review,
)
from finsentry.investigator.planning import (
    PlannedQuery,
    Planner,
    ValidatedPlan,
    query_key,
    validate_plan,
)
from finsentry.investigator.policy import (
    PolicyViolationError,
    admit_inference,
    admit_query,
    canonical_args,
    decide_stop,
    finish,
    next_query_id,
    record_hypothesis_round,
    record_inference,
    record_query,
    with_elapsed,
)
from finsentry.investigator.reports import abstention_report
from finsentry.mcp.tools.traces import GetFailingTracesResult

Clock = Callable[[], float]


class InvestigationFailedError(RuntimeError):
    """An investigation that could not finish. It carries the last good state so a runner can
    still account for the tool and inference calls already spent."""

    def __init__(self, message: str, state: InvestigationState) -> None:
        super().__init__(message)
        self.state = state


class Investigator(Protocol):
    agent_version: str

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult: ...


def start_investigation(
    incident_id: str,
    trigger: IncidentTrigger,
    window: TimeWindow,
    *,
    scope: AffectedScope | None = None,
    extra_gaps: list[DataGap] | None = None,
    budgets: Budgets | None = None,
) -> InvestigationState:
    """A fresh state with the tools' known data gaps already declared."""
    return InvestigationState(
        incident_id=incident_id,
        trigger=trigger,
        window=window,
        scope=scope or AffectedScope(),
        known_data_gaps=[*KNOWN_TOOL_GAPS, *(extra_gaps or [])],
        budgets=budgets or Budgets(),
    )


def _opening_query(state: InvestigationState) -> tuple[ToolName, dict[str, object]]:
    """The first read for a trigger: the tool whose evidence the investigation cannot do
    without (policy.CRITICAL_TOOLS), asked about the trigger's own scope and window."""
    t, w, scope = state.trigger, state.window.minutes, state.scope
    window: dict[str, object] = {"time_window_minutes": w}
    if scope.endpoint:
        window["endpoint"] = scope.endpoint
    by_kind: dict[TriggerKind, tuple[ToolName, dict[str, object]]] = {
        "faithfulness_block_cluster": (
            "get_failing_traces",
            {**window, "failure_type": "any", "limit": 50},
        ),
        "error_kind_surge": (
            "get_failing_traces",
            {**window, "failure_type": "error", "limit": 50},
        ),
        "judge_disagreement_cluster": (
            "search_traces",
            {
                "disagreement": True,
                "limit": 20,
                **({"ticker": scope.ticker} if scope.ticker else {}),
            },
        ),
        "red_team_miss": ("get_red_team_execution", {"execution_id": t.reference_id or ""}),
        "drift_degradation": ("get_drift_report", {}),
        "single_trace": ("get_trace_detail", {"app_trace_id": t.reference_id or ""}),
    }
    return by_kind[t.kind]


def spread(ids: list[str], k: int) -> list[str]:
    """k ids from across a list, first to last, so a sample is not just its head."""
    ids = list(dict.fromkeys(ids))
    if k >= len(ids):
        return ids
    if k == 1:
        return ids[:1]
    return [ids[round(i * (len(ids) - 1) / (k - 1))] for i in range(k)]


def merge_hypotheses(
    old: list[Hypothesis], new: list[Hypothesis], limit: int = 4
) -> list[Hypothesis]:
    """A later plan replaces a hypothesis it names again and may add new ones."""
    merged = {h.hypothesis_id: h for h in old}
    merged.update({h.hypothesis_id: h for h in new if h.hypothesis_id in merged})
    for h in new:
        if h.hypothesis_id not in merged and len(merged) < limit:
            merged[h.hypothesis_id] = h
    return list(merged.values())


class BoundedInvestigator:
    """Investigates one incident within its budgets, then reports a diagnosis or abstains."""

    def __init__(
        self, planner: Planner, *, tool_timeout_s: float = 20.0, model_timeout_s: float = 45.0
    ) -> None:
        self.planner = planner
        self.tool_timeout_s = tool_timeout_s
        self.model_timeout_s = model_timeout_s
        self.agent_version = f"bounded-investigator-1+{planner.name}"

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult:
        run = _Run(self, state, tools, clock)
        try:
            return await run.run()
        except InvestigationFailedError:
            raise
        except Exception as exc:
            raise InvestigationFailedError(f"{type(exc).__name__}: {exc}", run.state) from exc


class _Run:
    def __init__(
        self,
        owner: BoundedInvestigator,
        state: InvestigationState,
        tools: ReadOnlyAdapter,
        clock: Clock,
    ) -> None:
        self.owner, self.state, self.tools, self.clock = owner, state, tools, clock
        self.t0 = clock()
        self.results: list[ToolResult] = []
        self.proposed: list[Hypothesis] = []  # as the planner wrote them
        self.ledger: list[Hypothesis] = []  # as the results leave them
        self.assessments: dict[str, Assessment] = {}
        self.draft: ProposedVerification | None = None
        self.sampled: dict[str, set[str]] = {}  # sampled group key -> the queries that filled it
        self.notes: list[str] = []
        self.cut_short = False  # a ceiling or a failure stopped work the run had planned

    # time and admission

    def _tick(self) -> None:
        self.state = with_elapsed(self.state, self.clock() - self.t0)

    def _cap(self, per_call_s: float) -> float:
        left = self.state.budgets.max_wall_clock_s - (self.clock() - self.t0)
        return max(0.001, min(per_call_s, left))

    def _can_continue(self) -> bool:
        u, b = self.state.usage, self.state.budgets
        return (
            admit_inference(self.state).allowed
            and u.tool_calls < b.max_tool_calls
            and u.hypothesis_rounds < b.max_hypothesis_rounds
        )

    # one tool call

    async def _query(
        self, tool: ToolName, args: dict[str, object], separates: list[str], why: str | None = None
    ) -> ToolResult | None:
        """Run one read under a timeout, or None when the policy refuses it."""
        self._tick()
        admission = admit_query(self.state, tool, args, why)
        if not admission.allowed:
            if "identical" not in admission.reason:
                self.cut_short = True
                self.notes.append(f"{tool} not run: {admission.reason}")
            return None
        query_id = next_query_id(self.state)
        cap = self._cap(self.owner.tool_timeout_s)
        try:
            result = await asyncio.wait_for(self.tools.call(tool, query_id, **args), cap)
        except TimeoutError:
            result = ToolResult(
                query_id, tool, args, "unavailable", [], None, f"timed out after {cap:.1f}s", cap
            )
        self.state = record_query(
            self.state,
            ExecutedQuery(
                query_id=query_id,
                tool=tool,
                args=args,
                status=result.status,
                evidence=result.evidence,
                error=result.error,
                retry_justification=why,
                empty_unverified=result.empty_unverified,
                separates=separates,
            ),
            self.clock() - self.t0,
        )
        self.results.append(result)
        return result

    # the investigation

    async def run(self) -> InvestigationResult:
        opened = await self._open()
        if opened is not None:
            return opened
        plan = await self._plan(1)
        if plan is None:
            return self._abstain("the planner produced no usable plan", forced=True)
        self.proposed, self.draft = plan.hypotheses, plan.verification
        self.notes += plan.notes
        if not self._record(self.proposed):
            return self._abstain("no hypothesis round was available", forced=True)
        await self._execute(plan.queries)
        outcome = self._reassess(can_continue=self._can_continue())
        if isinstance(outcome, InvestigationResult):
            return outcome
        if outcome.decision == "continue":
            follow = await self._plan(2)
            if follow is not None:
                self.proposed = merge_hypotheses(self.proposed, follow.hypotheses)
                self.draft = follow.verification or self.draft
                self.notes += follow.notes
                await self._execute(follow.queries)
            else:
                self.cut_short = True
            outcome = self._reassess(can_continue=False)
            if isinstance(outcome, InvestigationResult):
                return outcome
        if outcome.decision == "diagnose":
            return self._diagnose(outcome)
        return self._abstain_from(outcome)

    async def _open(self) -> InvestigationResult | None:
        """Establish the incident and its blast radius. Returns a result only when nothing
        more can be learned: the critical source is down, or the trigger left no trace."""
        tool, args = _opening_query(self.state)
        first = await self._query(tool, args, [])
        if first is not None and first.status == "unavailable":
            first = await self._query(
                tool,
                args,
                [],
                why="the first attempt was unavailable, so the source may have recovered",
            )
        if decide_stop(self.state) == "critical_evidence_unavailable":
            return self._abstain(f"{tool} could not be read, so the incident cannot be examined")
        if first is None:
            return self._abstain("the opening query could not be run", forced=True)
        if first.status in ("empty", "rejected"):
            caveat = " It may have been a failed query." if first.empty_unverified else ""
            return self._abstain(
                f"the opening query {tool} returned {first.status}, so the trigger left no "
                f"record to examine.{caveat}"
            )
        return None

    async def _plan(self, round_no: int) -> ValidatedPlan | None:
        rejection = ""
        for attempt in range(2 if round_no == 1 else 1):
            self._tick()
            if not admit_inference(self.state).allowed:
                break
            digest = build_digest(self.state, self.results, self.ledger or None) + rejection
            self.state = record_inference(self.state)
            try:
                plan = await asyncio.wait_for(
                    self.owner.planner.plan(digest, round_no=round_no),
                    self._cap(self.owner.model_timeout_s),
                )
                return validate_plan(plan, self.state)
            except TimeoutError:
                self.notes.append(f"planner call {attempt + 1} timed out")
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.notes.append(f"planner call {attempt + 1} failed: {detail}")
                rejection = f"\n\nYour previous reply was rejected ({detail}). Reply again."
        self.cut_short = True
        return None

    def _record(self, ledger: list[Hypothesis]) -> bool:
        try:
            self.state = record_hypothesis_round(self.state, ledger)
        except PolicyViolationError as exc:
            self.notes.append(str(exc))
            self.cut_short = True
            return False
        self.ledger = ledger
        return True

    async def _execute(self, queries: list[PlannedQuery]) -> None:
        """Run the queries that separate hypotheses, in the order of how many they separate,
        until the budget says stop. A query that reads sampled traces first runs, or reuses,
        the listing the sample is taken from."""
        for q in queries:
            if await self._run_planned(q):
                return

    async def _run_planned(self, q: PlannedQuery) -> bool:
        """Run one planned query, or the sample it expands to. True when the budget refused
        it and the rest of the plan should not run. A sampled group is recorded under its key
        whatever happens, so a prediction about it reads exactly the traces taken for it."""
        argsets: list[dict[str, object]] = []
        try:
            source = q.sample_from
            if q.listing is not None:
                source, refused = await self._listing(*q.listing, q.separates)
                if refused:
                    return True
            argsets = self._expand(q, source)
            for args in argsets:
                self._tick()
                admission = admit_query(self.state, q.tool, args)
                if admission.allowed:
                    await self._query(q.tool, args, q.separates)
                elif "identical" not in admission.reason:
                    self.cut_short = True
                    self.notes.append(f"{q.tool} not run: {admission.reason}")
                    return True
            return False
        finally:
            if q.sample_from is not None or q.listing is not None:
                wanted = {canonical_args(a) for a in argsets}
                self.sampled.setdefault(q.key, set()).update(
                    e.query_id
                    for e in self.state.executed_queries
                    if e.tool == q.tool and canonical_args(e.args) in wanted
                )

    def scopes(self) -> Scopes:
        """The queries each prediction key covers. A plain query is every executed call with
        that tool and arguments, the opening query included. A sampled group is the traces
        taken for it."""
        found: dict[str, set[str]] = {}
        for e in self.state.executed_queries:
            found.setdefault(query_key(e.tool, e.args), set()).add(e.query_id)
        for key, ids in self.sampled.items():
            found.setdefault(key, set()).update(ids)
        return {key: frozenset(ids) for key, ids in found.items()}

    async def _listing(
        self, tool: ToolName, args: dict[str, object], separates: list[str]
    ) -> tuple[str | None, bool]:
        """The id of the query that listed these traces, running it if it has not run, and
        whether the budget refused it. The id is None when the listing returned no records."""
        key = canonical_args(args)
        done = next(
            (
                q
                for q in self.state.executed_queries
                if q.tool == tool and canonical_args(q.args) == key and q.status == "ok"
            ),
            None,
        )
        if done is not None:
            return done.query_id, False
        result = await self._query(tool, args, separates)
        if result is None:
            return None, True
        return (result.query_id if result.status == "ok" else None), False

    def _expand(self, q: PlannedQuery, source_id: str | None) -> list[dict[str, object]]:
        if q.sample_from is None and q.listing is None:
            return [q.args]
        source = next((e for e in self.state.executed_queries if e.query_id == source_id), None)
        ids = [r.record_id for r in (source.evidence if source else []) if r.kind == "trace"]
        if q.sample_class:
            listed = next((r.payload for r in self.results if r.query_id == source_id), None)
            if isinstance(listed, GetFailingTracesResult):
                wanted = {
                    t.app_trace_id for t in listed.traces if t.classification == q.sample_class
                }
                ids = [i for i in ids if i in wanted]
        return [{**q.args, "app_trace_id": i} for i in spread(ids, q.sample_size)]

    def _reassess(self, *, can_continue: bool) -> Review | InvestigationResult:
        ledger, self.assessments = assess(
            self.proposed, self.results, SYMPTOM_SIGNALS[self.state.trigger.kind], self.scopes()
        )
        if not self._record(ledger):
            return self._abstain("no hypothesis round was available", forced=True)
        unverified = any(r.empty_unverified for r in self.results)
        return review(
            self.ledger, self.assessments, can_continue=can_continue, unverified_empties=unverified
        )

    # the ending

    def _diagnose(self, outcome: Review) -> InvestigationResult:
        self._tick()
        reason = decide_stop(self.state, evidence_sufficient=True) or "sufficient_evidence"
        stopped = finish(self.state, reason)
        report = build_diagnosis(
            stopped,
            self.ledger,
            self.assessments,
            outcome,
            self.results,
            self.draft,
            self.notes,
            self.scopes(),
        )
        validation = validate_report(report, stopped)
        if validation.valid:
            self.state = stopped
            return InvestigationResult(report=report, state=stopped)
        self.notes.append(
            "the diagnosis report failed validation: " + "; ".join(validation.problems)
        )
        return self._abstain("the diagnosis did not pass report validation")

    def _abstain_from(self, outcome: Review) -> InvestigationResult:
        self.state.unresolved_questions = list(outcome.unresolved)
        self.notes += outcome.notes
        return self._abstain("", forced=self.cut_short)

    def _abstain(self, note: str, *, forced: bool = False) -> InvestigationResult:
        self._tick()
        reason = decide_stop(self.state, abstain=not forced) or "budget_exhausted"
        self.state = finish(self.state, reason)
        if note and note not in self.state.unresolved_questions:
            self.state.unresolved_questions = [*self.state.unresolved_questions, note]
        report = abstention_report(
            self.state, choose_verification(self.state, None, self.draft), notes=self.notes
        )
        validation = validate_report(report, self.state)
        if not validation.valid:
            raise InvestigationFailedError(
                f"the abstention report is invalid: {validation.problems}", self.state
            )
        return InvestigationResult(report=report, state=self.state)
