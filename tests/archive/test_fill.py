"""The fill planner and its preventive spend rule. Nothing here calls a gateway or a model."""

from __future__ import annotations

from finsentry.archive.coverage import Candidate, Row, Stored
from finsentry.archive.fill import TARGET_PER_COMPANY, can_afford, plan


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
