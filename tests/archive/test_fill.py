"""The fill planner and its preventive spend rule. Nothing here calls a gateway or a model."""

from __future__ import annotations

from finsentry.archive.coverage import Candidate, Row, Stored
from finsentry.archive.fill import (
    PER_CALL_CEILING,
    TARGET_PER_COMPANY,
    can_afford,
    plan,
    unrecorded_gateway_charge,
)


def _row(ticker: str, label: str, kinds: tuple[str, ...] = (), complete: bool = False) -> Row:
    stored = [Stored(f"e{i}", f"t{i}", k, True, True, "complete", 0) for i, k in enumerate(kinds)]
    done = stored[0] if complete else None
    return Row(Candidate(ticker, f"q {label}", label), stored, done, None, None)


def test_the_budget_is_checked_before_the_request_against_its_worst_case() -> None:
    assert can_afford(0.0, 0.062, 0.50)
    assert can_afford(0.438, 0.062, 0.50)
    assert not can_afford(0.439, 0.062, 0.50)
    assert not can_afford(0.50, 0.001, 0.50)


def test_the_homepage_question_is_asked_first_and_counts_toward_its_company() -> None:
    rows = [_row("AMZN", f"A{i}") for i in range(8)]
    rows.append(
        Row(Candidate("AMZN", "home", "AMZN-homepage", homepage=True), [], None, None, None)
    )
    slots = plan(rows)
    assert slots[0].label == "AMZN-homepage"
    assert len(slots) == TARGET_PER_COMPANY  # the homepage question plus four from the seed


def test_a_company_at_its_target_is_not_asked_again_and_complete_questions_are_reused() -> None:
    rows = [_row("AAPL", f"done{i}", ("success",), complete=True) for i in range(5)]
    rows += [
        _row("AAPL", "extra"),
        _row("MSFT", "m1", ("success",), complete=True),
        _row("MSFT", "m2"),
    ]
    assert [s.label for s in plan(rows)] == ["m2"]


def test_unstored_questions_come_before_stored_incomplete_ones_and_blocked_ones_are_skipped() -> (
    None
):
    rows = [
        _row("JPM", "blocked-only", ("blocked",)),
        _row("JPM", "partial", ("success",)),
        _row("JPM", "fresh"),
    ]
    assert [s.label for s in plan(rows, target=5)] == ["fresh", "partial"]


def test_companies_furthest_from_the_target_take_turns_so_a_stop_leaves_coverage_even() -> None:
    rows = [_row("A", f"a{i}") for i in range(3)] + [_row("B", f"b{i}") for i in range(3)]
    rows += [_row("B", "bdone", ("success",), complete=True)]
    labels = [s.label for s in plan(rows, target=3)]
    assert labels[:2] == ["a0", "a1"] or labels[0] == "a0"
    assert labels.count("a0") + labels.count("a1") + labels.count("a2") == 3
    assert sum(1 for x in labels if x.startswith("b")) == 2


def test_an_excluded_company_is_never_planned_and_does_not_count() -> None:
    rows = [_row("AAPL", "a1"), _row("AAPL", "a2"), _row("NVDA", "n1")]
    assert [s.label for s in plan(rows, exclude=frozenset({"AAPL"}))] == ["n1"]


def test_unasked_only_drops_a_question_that_was_stored_but_is_not_complete() -> None:
    rows = [_row("JPM", "fresh"), _row("JPM", "partial", ("success",))]
    assert [s.label for s in plan(rows, unasked_only=True)] == ["fresh"]
    assert [s.label for s in plan(rows)] == ["fresh", "partial"]


def test_unrecorded_gateway_usage_is_charged_at_the_ceiling_and_never_as_zero() -> None:
    # Local input rails make no Gemini call.
    assert unrecorded_gateway_charge(403, {"error": "request blocked by input rail"}, None) == 0.0
    # Only the faithfulness rail calls Gemini among the output rails.
    assert unrecorded_gateway_charge(422, {"rail": "schema"}, "blocked") == 0.0
    faith = {"rail": "faithfulness", "reason": "low_faithfulness"}
    assert unrecorded_gateway_charge(422, faith, "blocked") == PER_CALL_CEILING
    # A retrieval block answers 200 with no cost and never reaches the output rails.
    assert unrecorded_gateway_charge(200, {}, "blocked") == 0.0
    # A delivered answer with no recorded cost, an error and a timeout are all unknown.
    assert unrecorded_gateway_charge(200, {}, "success") == PER_CALL_CEILING
    assert unrecorded_gateway_charge(200, {}, None) == PER_CALL_CEILING
    assert unrecorded_gateway_charge(500, {}, None) == PER_CALL_CEILING
    assert unrecorded_gateway_charge(504, {"error": "request deadline exceeded"}, None) == (
        PER_CALL_CEILING
    )
