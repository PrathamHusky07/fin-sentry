"""A citation is valid only if a query in this investigation returned the record."""

from __future__ import annotations

import pytest

from finsentry.investigator.citations import parse_report, retrieved_evidence, validate_report
from finsentry.investigator.contracts import (
    ABSTENTION_STATEMENT,
    EvidenceRef,
    ExecutedQuery,
    IncidentReport,
    InvestigationState,
    ProposedVerification,
)
from finsentry.investigator.policy import finish, record_query
from finsentry.investigator.reports import abstention_report
from tests.investigator.helpers import make_hypothesis, make_state

REAL = EvidenceRef(kind="trace", record_id="t-real")
FORGED = EvidenceRef(kind="trace", record_id="t-forged")
VERIFY = ProposedVerification(
    kind="read_only_query",
    tool="get_drift_report",
    args={},
    rationale="read the last canary reading",
)


def _investigated() -> InvestigationState:
    """One query ran and returned t-real, and one hypothesis in the ledger is supported by it."""
    state = make_state(hypotheses=[make_hypothesis("h1", supporting=[REAL], status="supported")])
    query = ExecutedQuery(
        query_id="q1",
        tool="get_failing_traces",
        args={"limit": 5},
        status="ok",
        evidence=[EvidenceRef(kind="query_result", record_id="q1"), REAL],
    )
    return finish(record_query(state, query, 1.0), "sufficient_evidence")


def _diagnosis(**overrides: object) -> IncidentReport:
    fields: dict[str, object] = {
        "incident_id": "inc-1",
        "outcome": "diagnosis",
        "ranked_hypotheses": [
            {
                "hypothesis_id": "h1",
                "rank": 1,
                "subsystem": "retrieval",
                "statement": "a retrieved chunk is stale",
                "confidence": "medium",
                "supporting": [REAL],
            }
        ],
        "correlations": [{"statement": "consistent with a shared chunk", "evidence": [REAL]}],
        "tests_actually_run": ["q1"],
        "proposed_verification": VERIFY,
        "stopping_reason": "sufficient_evidence",
    }
    fields.update(overrides)
    return IncidentReport.model_validate(fields)


def test_a_report_citing_only_retrieved_records_is_valid() -> None:
    assert validate_report(_diagnosis(), _investigated()).valid


def test_retrieved_evidence_is_exactly_what_the_queries_returned() -> None:
    assert retrieved_evidence(_investigated()) == {
        EvidenceRef(kind="query_result", record_id="q1"),
        REAL,
    }


def test_a_plausible_but_never_retrieved_citation_is_rejected() -> None:
    report = _diagnosis(correlations=[{"statement": "consistent with x", "evidence": [FORGED]}])
    result = validate_report(report, _investigated())
    assert not result.valid
    assert any("trace:t-forged" in p and "no query" in p for p in result.problems)


def test_a_forged_support_on_the_top_hypothesis_invalidates_the_report() -> None:
    ranked = [
        {
            "hypothesis_id": "h1",
            "rank": 1,
            "subsystem": "retrieval",
            "statement": "s",
            "confidence": "high",
            "supporting": [FORGED],
        }
    ]
    result = validate_report(_diagnosis(ranked_hypotheses=ranked), _investigated())
    assert not result.valid


def test_a_real_id_of_the_wrong_kind_is_not_a_retrieved_record() -> None:
    wrong_kind = EvidenceRef(kind="red_team_execution", record_id="t-real")
    report = _diagnosis(correlations=[{"statement": "consistent with x", "evidence": [wrong_kind]}])
    assert not validate_report(report, _investigated()).valid


def test_a_citation_valid_in_another_investigation_is_rejected_in_this_one() -> None:
    other = make_state("inc-2", status="stopped", stopping_reason="sufficient_evidence")
    report = _diagnosis(incident_id="inc-2")
    assert not validate_report(report, other).valid  # nothing was retrieved in inc-2


def test_a_query_that_returned_nothing_makes_nothing_citable() -> None:
    state = make_state()
    unavailable = ExecutedQuery(
        query_id="q1", tool="get_failing_traces", args={}, status="unavailable", error="offline"
    )
    assert retrieved_evidence(record_query(state, unavailable, 0.0)) == frozenset()


def test_the_top_hypothesis_must_cite_something() -> None:
    ranked = [
        {
            "hypothesis_id": "h1",
            "rank": 1,
            "subsystem": "retrieval",
            "statement": "s",
            "confidence": "low",
        }
    ]
    result = validate_report(_diagnosis(ranked_hypotheses=ranked), _investigated())
    assert any("no supporting evidence" in p for p in result.problems)


def test_a_hypothesis_outside_the_ledger_is_rejected() -> None:
    ranked = [
        {
            "hypothesis_id": "h-invented",
            "rank": 1,
            "subsystem": "retrieval",
            "statement": "s",
            "confidence": "low",
            "supporting": [REAL],
        }
    ]
    result = validate_report(_diagnosis(ranked_hypotheses=ranked), _investigated())
    assert any("not in the ledger" in p for p in result.problems)


def test_a_malformed_report_is_rejected_before_validation() -> None:
    assert parse_report({"incident_id": "inc-1", "outcome": "diagnosis"}) is None
    assert parse_report("not a report") is None
    bad_confidence = _diagnosis().model_dump()
    bad_confidence["ranked_hypotheses"][0]["confidence"] = "certain"
    assert parse_report(bad_confidence) is None
    assert parse_report(_diagnosis().model_dump()) is not None


def test_a_report_may_not_say_a_tool_ran_when_it_was_unavailable() -> None:
    state = make_state()
    state = record_query(
        state,
        ExecutedQuery(
            query_id="q1", tool="search_traces", args={}, status="unavailable", error="down"
        ),
        0.0,
    )
    state = finish(state, "justified_abstention")
    honest = abstention_report(state)
    assert validate_report(honest, state).valid
    assert honest.tool_unavailable == ["search_traces"] and honest.empty_results == []
    # Coercing the unavailable query into an empty result is the lie being guarded against.
    coerced = honest.model_copy(update={"tool_unavailable": [], "empty_results": ["q1"]})
    problems = validate_report(coerced, state).problems
    assert any("not an empty result" in p for p in problems)
    assert any("omits search_traces" in p for p in problems)


def test_a_report_may_not_list_an_available_tool_as_unavailable() -> None:
    state = _investigated()
    report = _diagnosis(tool_unavailable=["get_failing_traces"])
    assert any("but it ran" in p for p in validate_report(report, state).problems)


def test_a_proposed_verification_must_be_a_real_unrun_precise_step() -> None:
    state = _investigated()

    def verdict(**v: object) -> list[str]:
        return list(
            validate_report(
                _diagnosis(proposed_verification=ProposedVerification.model_validate(v)), state
            ).problems
        )

    assert verdict(kind="red_team_scenario", scenario_id="DI-001", rationale="r") == []
    assert any(
        "unknown" in p
        for p in verdict(kind="red_team_scenario", scenario_id="NOPE-9", rationale="r")
    )
    bad_args = verdict(
        kind="read_only_query", tool="get_drift_report", args={"x": 1}, rationale="r"
    )
    assert any("not a valid call" in p for p in bad_args)
    repeated = verdict(
        kind="read_only_query", tool="get_failing_traces", args={"limit": 5}, rationale="r"
    )
    assert any("already executed" in p for p in repeated)


def test_a_proposed_read_only_query_is_held_to_the_full_argument_constraints() -> None:
    """A signature that binds is not enough: the limit, identifier and type rules that would
    reject the call before a real run reject the proposal too."""
    state = _investigated()

    def problems(tool: str, args: dict[str, object]) -> list[str]:
        report = _diagnosis(
            proposed_verification=ProposedVerification(
                kind="read_only_query",
                tool=tool,
                args=args,
                rationale="r",  # type: ignore[arg-type]
            )
        )
        return [p for p in validate_report(report, state).problems if "valid call" in p]

    assert problems("search_traces", {"limit": 0})
    assert problems("search_traces", {"limit": 101})
    assert problems("get_red_team_execution", {"execution_id": "not-a-uuid"})
    assert problems("list_red_team_executions", {"scenario_id": "S" * 17})
    assert problems("get_failing_traces", {"limit": "many"})
    assert not problems("search_traces", {"limit": 20, "disagreement": True})


# The validator enforces the report against the ledger itself, not against its builder.


def _two_hypotheses(**second: object) -> InvestigationState:
    rival = make_hypothesis("h2", symptom="incident", subsystem="judges", **second)
    state = make_state(
        hypotheses=[make_hypothesis("h1", supporting=[REAL], status="supported"), rival]
    )
    query = ExecutedQuery(
        query_id="q1",
        tool="get_failing_traces",
        args={"limit": 5},
        status="ok",
        evidence=[EvidenceRef(kind="query_result", record_id="q1"), REAL],
    )
    return finish(record_query(state, query, 1.0), "sufficient_evidence")


def _ranked(
    hid: str, rank: int, subsystem: str, statement: str, confidence: str = "medium"
) -> dict:  # type: ignore[type-arg]
    return {
        "hypothesis_id": hid,
        "rank": rank,
        "subsystem": subsystem,
        "statement": statement,
        "confidence": confidence,
        "supporting": [REAL] if hid == "h1" else [],
    }


def _problems(state: InvestigationState, ranked: list[dict]) -> list[str]:  # type: ignore[type-arg]
    report = _diagnosis(ranked_hypotheses=ranked)
    return list(validate_report(report, state).problems)


def test_a_ranked_statement_must_be_the_ledgers_statement() -> None:
    state = _two_hypotheses()
    rival_statement = "a retrieved chunk is stale"  # make_hypothesis's default statement
    good = [
        _ranked("h1", 1, "retrieval", "a retrieved chunk is stale"),
        _ranked("h2", 2, "judges", rival_statement),
    ]
    assert _problems(state, good) == []
    rewritten = [_ranked("h1", 1, "retrieval", "the model hallucinated"), good[1]]
    assert any("other than the ledger" in p for p in _problems(state, rewritten))


def test_a_ranking_must_not_put_a_worse_supported_hypothesis_first() -> None:
    state = _two_hypotheses(status="weakened", contradicting=[REAL])
    inverted = [
        _ranked("h2", 1, "judges", "a retrieved chunk is stale"),
        _ranked("h1", 2, "retrieval", "a retrieved chunk is stale"),
    ]
    problems = _problems(state, inverted)
    assert any("worse supported" in p for p in problems)
    assert any("not supported in the ledger" in p for p in problems)


def test_high_confidence_needs_a_rival_the_ledger_holds_as_refuted() -> None:
    def high(state: InvestigationState) -> list[str]:
        ranked = [
            _ranked("h1", 1, "retrieval", "a retrieved chunk is stale", "high"),
            _ranked("h2", 2, "judges", "a retrieved chunk is stale"),
        ]
        return _problems(state, ranked)

    assert any("high confidence" in p for p in high(_two_hypotheses()))
    refuted = _two_hypotheses(status="refuted", contradicting=[REAL])
    assert not any("high confidence" in p for p in high(refuted))


def test_a_controlled_test_causal_claim_must_cite_a_red_team_execution() -> None:
    claim = {"statement": "x caused y", "basis": "controlled_test", "evidence": [REAL]}
    result = validate_report(_diagnosis(causal_claims=[claim]), _investigated())
    assert any("no Red Team execution" in p for p in result.problems)


def test_a_report_for_a_different_incident_or_stop_reason_is_rejected() -> None:
    state = _investigated()
    assert not validate_report(_diagnosis(incident_id="inc-9"), state).valid
    assert not validate_report(_diagnosis(stopping_reason="budget_exhausted"), state).valid


def test_an_abstention_is_a_valid_outcome_with_no_evidence_at_all() -> None:
    state = finish(make_state(), "justified_abstention")
    report = abstention_report(state)
    assert report.outcome == "abstention" and report.abstention_statement == ABSTENTION_STATEMENT
    assert validate_report(report, state).valid


@pytest.mark.parametrize(
    "trigger_kind, tool",
    [
        ("faithfulness_block_cluster", "get_failing_traces"),
        ("judge_disagreement_cluster", "search_traces"),
        ("error_kind_surge", "get_failing_traces"),
        ("drift_degradation", "get_drift_report"),
    ],
)
def test_the_default_verification_for_each_trigger_is_a_valid_read_only_query(
    trigger_kind: str, tool: str
) -> None:
    from finsentry.investigator.contracts import IncidentTrigger

    state = make_state(trigger=IncidentTrigger(kind=trigger_kind, description="d"))  # type: ignore[arg-type]
    state = finish(state, "justified_abstention")
    report = abstention_report(state)
    assert report.proposed_verification.tool == tool
    assert validate_report(report, state).valid


def test_the_default_verification_moves_on_when_it_was_already_run() -> None:
    state = make_state()
    first = abstention_report(finish(state, "justified_abstention")).proposed_verification
    ran = record_query(
        state,
        ExecutedQuery(
            query_id="q1",
            tool=first.tool,  # type: ignore[arg-type]
            args=first.args or {},
            status="empty",
            evidence=[EvidenceRef(kind="query_result", record_id="q1")],
        ),
        0.0,
    )
    second = abstention_report(finish(ran, "justified_abstention")).proposed_verification
    assert (second.tool, second.args) != (first.tool, first.args)
