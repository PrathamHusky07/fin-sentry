"""A query is worth running only when it tells hypotheses apart.

That needs two hypotheses with an explicit prediction for the query and a real difference
between those predictions. A hypothesis that says nothing about a query is untested by it. It
does not count as predicting the opposite of one that does.
"""

from __future__ import annotations

from finsentry.investigator.contracts import Signal, Subsystem
from finsentry.investigator.planning import (
    Plan,
    PlanHypothesis,
    PlanPrediction,
    QuerySpec,
    validate_plan,
)
from tests.investigator.helpers import make_state

DRIFT = QuerySpec(tool="get_drift_report")
BLOCKS = QuerySpec(tool="get_failing_traces", args_json='{"failure_type":"blocked","limit":50}')
ERRORS = QuerySpec(tool="get_failing_traces", args_json='{"failure_type":"error","limit":50}')
RED_TEAM = QuerySpec(tool="list_red_team_executions", args_json='{"limit":20}')


def predict(
    query: QuerySpec,
    signal: Signal,
    *,
    expect: bool = True,
    subject: str | None = None,
) -> PlanPrediction:
    return PlanPrediction(
        query=query, signal=signal, expect=expect, subject=subject, description=f"{signal}"
    )


def hypothesis(
    hid: str, subsystem: Subsystem, *predictions: PlanPrediction, symptom: str = "s"
) -> PlanHypothesis:
    return PlanHypothesis(
        hypothesis_id=hid,
        symptom=symptom,
        subsystem=subsystem,
        statement=f"a fault in {subsystem}",
        predictions=list(predictions),
    )


def queries_of(*hypotheses: PlanHypothesis) -> dict[str, list[str]]:
    plan = validate_plan(Plan(hypotheses=list(hypotheses)), make_state())
    return {q.tool + str(sorted(q.args.items())): q.separates for q in plan.queries}


def kept_tools(*hypotheses: PlanHypothesis) -> list[str]:
    return [q.tool for q in validate_plan(Plan(hypotheses=list(hypotheses)), make_state()).queries]


# The rival's own query keeps both hypotheses usable, so only the query under test varies.
RIVAL = predict(RED_TEAM, "rail_regression")
OTHER = predict(RED_TEAM, "rail_working")


def test_a_query_only_one_hypothesis_mentions_does_not_discriminate() -> None:
    h1 = hypothesis("h1", "judges", predict(DRIFT, "judge_drift"), RIVAL)
    h2 = hypothesis("h2", "output_rails", OTHER)
    assert "get_drift_report" not in kept_tools(h1, h2)


def test_identical_explicit_predictions_do_not_discriminate() -> None:
    h1 = hypothesis("h1", "judges", predict(DRIFT, "judge_drift"), RIVAL)
    h2 = hypothesis("h2", "retrieval", predict(DRIFT, "judge_drift"), OTHER)
    assert "get_drift_report" not in kept_tools(h1, h2)


def test_a_silent_third_hypothesis_does_not_turn_identical_predictions_into_a_difference() -> None:
    h1 = hypothesis("h1", "judges", predict(DRIFT, "judge_drift"), RIVAL)
    h2 = hypothesis("h2", "retrieval", predict(DRIFT, "judge_drift"), OTHER)
    h3 = hypothesis("h3", "output_rails", OTHER)
    assert "get_drift_report" not in kept_tools(h1, h2, h3)


def test_opposed_explicit_predictions_discriminate_and_name_the_hypotheses_they_separate() -> None:
    h1 = hypothesis("h1", "judges", predict(DRIFT, "judge_drift", expect=True), RIVAL)
    h2 = hypothesis("h2", "retrieval", predict(DRIFT, "judge_drift", expect=False), OTHER)
    h3 = hypothesis("h3", "output_rails", OTHER)
    kept = queries_of(h1, h2, h3)
    assert kept["get_drift_report[]"] == ["h1", "h2"]


def test_different_signals_from_one_query_discriminate() -> None:
    """Blocks and errors can each be present or absent in one listing, so the listing can
    favor one hypothesis over the other."""
    h1 = hypothesis("h1", "output_rails", predict(BLOCKS, "block_cluster"), RIVAL)
    h2 = hypothesis("h2", "downstream_model", predict(BLOCKS, "judge_failures"), OTHER)
    assert "get_failing_traces" in kept_tools(h1, h2)


def test_different_subjects_of_one_signal_discriminate() -> None:
    h1 = hypothesis("h1", "output_rails", predict(RED_TEAM, "rail_regression", subject="OUT-001"))
    h2 = hypothesis("h2", "input_rails", predict(RED_TEAM, "rail_regression", subject="DI-001"))
    assert "list_red_team_executions" in kept_tools(h1, h2)
