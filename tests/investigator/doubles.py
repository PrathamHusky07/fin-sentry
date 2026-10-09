"""Scripted investigators for testing the harness itself.

These are not agents and not baselines. Each one follows the case's own recipe and then
reports in a fixed style, so a test can show what the scorer does with an ideal report, a
confident wrong one, a forged citation, and so on. They read the ground truth, which a real
investigator cannot.
"""

from __future__ import annotations

from typing import Literal

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.contracts import (
    EvidenceRef,
    ExecutedQuery,
    Hypothesis,
    IncidentReport,
    InvestigationResult,
    InvestigationState,
    PredictedObservation,
    ProposedVerification,
    RankedHypothesis,
    Subsystem,
)
from finsentry.investigator.evaluation.types import IncidentCase
from finsentry.investigator.loop import Clock
from finsentry.investigator.policy import (
    admit_query,
    canonical_args,
    decide_stop,
    finish,
    next_query_id,
    record_hypothesis_round,
    record_query,
)
from finsentry.investigator.reports import abstention_report

Style = Literal[
    "oracle",
    "confident_wrong",
    "hedged_wrong",
    "forger",
    "observational_causal",
    "overspender",
    "always_diagnose",
]

_PROBE_ARGS: dict[str, dict[str, object]] = {
    "get_drift_report": {},
    "get_failing_traces": {"failure_type": "any", "time_window_minutes": 15},
    "get_judge_scores": {"app_trace_id": "probe-1"},
    "search_traces": {"limit": 5, "query_contains": "probe"},
    "get_trace_detail": {"app_trace_id": "probe-1"},
    "list_red_team_executions": {"limit": 5, "outcome": "missed"},
    "search_prompt_injections": {"time_window_minutes": 15},
    "get_red_team_execution": {"execution_id": "probe-1"},
    "explain_guardrail_decision": {"app_trace_id": "probe-1"},
}


class ScriptedInvestigator:
    def __init__(self, case: IncidentCase, style: Style) -> None:
        self.case = case
        self.style = style
        self.agent_version = f"scripted-{style}"

    async def _run(
        self,
        state: InvestigationState,
        tools: ReadOnlyAdapter,
        clock: Clock,
        tool: str,
        args: dict[str, object],
    ) -> InvestigationState:
        justification: str | None = None
        for _ in range(2):
            if not admit_query(state, tool, args, justification).allowed:
                return state
            query_id = next_query_id(state)
            res = await tools.call(tool, query_id, **args)
            state = record_query(
                state,
                ExecutedQuery(
                    query_id=query_id,
                    tool=res.tool,
                    args=args,
                    status=res.status,
                    evidence=res.evidence,
                    error=res.error,
                    retry_justification=justification,
                ),
                clock(),
            )
            if res.status != "unavailable":
                return state
            justification = "the source may have recovered"
        return state

    def _verification(self, state: InvestigationState) -> ProposedVerification:
        truth = self.case.truth
        if truth.acceptable_scenarios:
            return ProposedVerification(
                kind="red_team_scenario",
                scenario_id=sorted(truth.acceptable_scenarios)[0],
                rationale="exercise the defense with a controlled input",
            )
        executed = {(q.tool, canonical_args(q.args)) for q in state.executed_queries}
        for tool in sorted(truth.acceptable_tools):
            if (tool, canonical_args(_PROBE_ARGS[tool])) not in executed:
                return ProposedVerification(
                    kind="read_only_query",
                    tool=tool,  # type: ignore[arg-type]
                    args=_PROBE_ARGS[tool],
                    rationale="confirm the finding with one more read",
                )
        raise AssertionError("no unexecuted acceptable verification")

    def _wrong_subsystem(self) -> Subsystem:
        truth = self.case.truth
        if truth.symptom_subsystem and truth.symptom_subsystem not in truth.true_subsystems:
            return truth.symptom_subsystem
        return next(
            s
            for s in ("input_rails", "downstream_model", "event_pipeline")
            if s not in truth.true_subsystems
        )  # type: ignore[return-value]

    async def investigate(
        self, state: InvestigationState, tools: ReadOnlyAdapter, clock: Clock
    ) -> InvestigationResult:
        truth = self.case.truth
        recipe = list(truth.recipe)
        if self.style == "overspender":
            recipe = [("list_red_team_executions", {"limit": i}) for i in range(1, 7)] + recipe
        for tool, args in recipe:
            state = await self._run(state, tools, clock, tool, dict(args))

        retrieved = {r for q in state.executed_queries for r in q.evidence}
        if truth.expected_outcome == "abstention" and self.style != "always_diagnose":
            state = finish(state, decide_stop(state, abstain=True) or "justified_abstention")
            return InvestigationResult(
                report=abstention_report(state, self._verification(state)), state=state
            )

        wrong = self.style in ("confident_wrong", "hedged_wrong", "always_diagnose")
        subsystems: list[Subsystem] = (
            [self._wrong_subsystem()] if wrong else sorted(truth.true_subsystems)  # type: ignore[type-var]
        )
        support = [r for r in truth.required_evidence if r in retrieved]
        if not support:
            support = [r for r in retrieved if r.kind != "query_result"][:1]
        if not support:
            # Nothing was retrieved, so a diagnosis can only cite a record it never saw.
            support = [EvidenceRef(kind="trace", record_id="never-retrieved-9999")]
        against = [r for r in truth.contradicting_required if r in retrieved]
        confidence = "low" if self.style == "hedged_wrong" else "high" if wrong else "medium"
        ledger = [
            Hypothesis(
                hypothesis_id=f"h{i}",
                statement=f"Cause in {s}: {' '.join(truth.cause_markers)}",
                subsystem=s,
                predicted_observations=[
                    PredictedObservation(tool="search_traces", description="traces share it")
                ],
                supporting=support,
                contradicting=against,
                status="supported",
            )
            for i, s in enumerate(subsystems, 1)
        ]
        if self.style == "always_diagnose":
            # A guess does not ask the policy first, so it reaches a report the policy refused.
            state = state.model_copy(update={"hypotheses": ledger})
        else:
            state = record_hypothesis_round(state, ledger)
        state = finish(state, "sufficient_evidence")
        ranked = [
            RankedHypothesis(
                hypothesis_id=h.hypothesis_id,
                rank=i,
                subsystem=h.subsystem,
                statement=h.statement,
                confidence=confidence,
                supporting=h.supporting,
                contradicting=h.contradicting,
            )
            for i, h in enumerate(ledger, 1)
        ]
        extra: dict[str, object] = {}
        statement = ranked[0].statement
        if self.style in ("observational_causal", "confident_wrong", "always_diagnose"):
            extra["causal_claims"] = [
                {
                    "statement": f"{statement} caused the incident",
                    "basis": "observational",
                    "evidence": support,
                }
            ]
        else:
            extra["correlations"] = [
                {"statement": f"consistent with: {statement}", "evidence": support}
            ]
        if self.style == "forger":
            forged = EvidenceRef(kind="trace", record_id="never-retrieved-9999")
            extra["observations"] = [{"statement": "a plausible trace", "evidence": [forged]}]
        report = IncidentReport.model_validate(
            {
                "incident_id": state.incident_id,
                "outcome": "diagnosis",
                "ranked_hypotheses": ranked,
                "evidence_against": [
                    {
                        "hypothesis_id": "h1",
                        "statement": "cuts against the symptom",
                        "evidence": against,
                    }
                ]
                if against and not wrong
                else [],
                "tests_actually_run": [q.query_id for q in state.executed_queries],
                "empty_results": [
                    q.query_id for q in state.executed_queries if q.status == "empty"
                ],
                "tool_unavailable": sorted(
                    {q.tool for q in state.executed_queries if q.status == "unavailable"}
                ),
                "proposed_verification": self._verification(state),
                "stopping_reason": "sufficient_evidence",
                **extra,
            }
        )
        return InvestigationResult(report=report, state=state)
