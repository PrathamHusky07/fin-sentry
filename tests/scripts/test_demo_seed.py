"""Tests for scripts/demo_seed.py. None of them touches the network, Docker or a model: they check
the committed seed, the idempotent selection and the two parsers the commands rely on."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from demo_seed import (  # noqa: E402, I001
    SEED_DIR,
    free_memory_percent,
    load_questions,
    missing_questions,
    retention_is_unbounded,
)


def test_the_seed_holds_forty_questions_eight_for_each_of_five_companies() -> None:
    questions = load_questions()
    assert len(questions) == 40
    per_company = {
        t: sum(q["ticker"] == t for q in questions) for t in {q["ticker"] for q in questions}
    }
    assert per_company == {"AAPL": 8, "MSFT": 8, "AMZN": 8, "NVDA": 8, "JPM": 8}
    assert len({q["id"] for q in questions}) == 40, "ids are unique"
    assert len({(q["ticker"], q["query"]) for q in questions}) == 40, "no question is listed twice"


def test_a_stored_execution_of_any_outcome_removes_a_question_from_the_missing_list() -> None:
    questions = load_questions()
    first, second = questions[0], questions[1]
    stored = {(first["ticker"], first["query"])}
    assert missing_questions(questions, stored) == questions[1:]
    assert missing_questions(questions, stored) == missing_questions(
        questions, stored
    )  # idempotent
    everything = {(q["ticker"], q["query"]) for q in questions}
    assert missing_questions(questions, everything) == []
    assert second in missing_questions(questions, stored)


def test_the_amazon_record_is_marked_historical_and_names_what_was_not_recovered() -> None:
    record = json.loads((SEED_DIR / "amzn-disagreement-v1.json").read_text())
    assert record["status"].startswith("HISTORICAL")
    assert record["app_trace_id"] == "96bca4b5-f707-4a93-b421-2674032849b5"
    assert record["recovered_fields"]["flash_judge"]["faithfulness_score"] == 1.0
    assert record["recovered_fields"]["frontier_judge"]["faithfulness_score"] == 0.0
    assert "event_id" in record["not_recovered"]


def test_free_memory_is_read_from_memory_pressure_output() -> None:
    assert (
        free_memory_percent(
            "The system has 25769803776 (1572864 pages)\nSystem-wide memory free percentage: 41%\n"
        )
        == 41
    )
    with pytest.raises(ValueError):
        free_memory_percent("no percentage here")


def test_retention_is_unbounded_only_when_the_topic_says_minus_one() -> None:
    limited = "cleanup.policy  delete  DEFAULT_CONFIG\nretention.ms  604800000  DEFAULT_CONFIG\n"
    unbounded = "cleanup.policy  delete  DEFAULT_CONFIG\nretention.ms  -1  DYNAMIC_TOPIC_CONFIG\n"
    assert not retention_is_unbounded(limited)
    assert retention_is_unbounded(unbounded)
    assert not retention_is_unbounded("")
