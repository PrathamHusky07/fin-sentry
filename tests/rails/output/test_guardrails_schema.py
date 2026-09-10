"""Phase 3 golden matrix tests for SchemaEnforcementRail."""
from __future__ import annotations

import json

import pytest

from finsentry.rails.output.guardrails_schema import SchemaEnforcementRail

RETRIEVED = {"chunk-1", "chunk-2", "chunk-3"}


def _valid_json(
    answer: str = "Apple revenue was $94.9B.",
    citations: list[dict[str, str]] | None = None,
    confidence: str = "high",
) -> str:
    if citations is None:
        citations = [{"chunk_id": "chunk-1", "quote": "Revenue $94.9B"}]
    return json.dumps({"answer": answer, "citations": citations, "confidence": confidence})


@pytest.fixture
def rail() -> SchemaEnforcementRail:
    return SchemaEnforcementRail()


# --- golden matrix ---


def test_valid_answer_with_valid_citations_passes(rail: SchemaEnforcementRail) -> None:
    decision = rail.check(_valid_json(), RETRIEVED)
    assert decision.outcome == "pass"


def test_valid_answer_empty_citations_confidence_low_passes(rail: SchemaEnforcementRail) -> None:
    payload = json.dumps({"answer": "No info found.", "citations": [], "confidence": "low"})
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "pass"


def test_valid_answer_empty_citations_confidence_medium_blocks(
    rail: SchemaEnforcementRail,
) -> None:
    payload = json.dumps(
        {"answer": "No info found.", "citations": [], "confidence": "medium"}
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "empty_citations_with_non_low_confidence"


def test_valid_answer_empty_citations_confidence_high_blocks(
    rail: SchemaEnforcementRail,
) -> None:
    payload = json.dumps(
        {"answer": "No info found.", "citations": [], "confidence": "high"}
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "empty_citations_with_non_low_confidence"


def test_hallucinated_chunk_id_blocks(rail: SchemaEnforcementRail) -> None:
    payload = _valid_json(
        citations=[{"chunk_id": "ghost-99", "quote": "hallucinated fact"}]
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "hallucinated_citation"
    assert "ghost-99" in decision.details["hallucinated_ids"]


def test_partial_hallucination_blocks_with_correct_counts(
    rail: SchemaEnforcementRail,
) -> None:
    payload = _valid_json(
        citations=[
            {"chunk_id": "chunk-1", "quote": "Revenue $94.9B"},
            {"chunk_id": "chunk-2", "quote": "Operating income $29.6B"},
            {"chunk_id": "ghost-99", "quote": "hallucinated fact"},
        ]
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "hallucinated_citation"
    assert decision.details["hallucinated_ids"] == ["ghost-99"]
    assert decision.details["surviving_ids_count"] == 2


def test_malformed_json_blocks(rail: SchemaEnforcementRail) -> None:
    decision = rail.check("{not valid json", RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "malformed_json"


def test_missing_answer_field_blocks(rail: SchemaEnforcementRail) -> None:
    payload = json.dumps({"citations": [], "confidence": "low"})
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "schema_violation"


def test_invalid_confidence_value_blocks(rail: SchemaEnforcementRail) -> None:
    payload = json.dumps(
        {
            "answer": "Revenue was $94.9B.",
            "citations": [{"chunk_id": "chunk-1", "quote": "Revenue $94.9B"}],
            "confidence": "certain",
        }
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "schema_violation"


def test_citation_quote_over_300_chars_blocks(rail: SchemaEnforcementRail) -> None:
    long_quote = "x" * 301
    payload = json.dumps(
        {
            "answer": "Revenue was $94.9B.",
            "citations": [{"chunk_id": "chunk-1", "quote": long_quote}],
            "confidence": "high",
        }
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "block"
    assert decision.reason == "schema_violation"


def test_duplicate_citations_same_chunk_id_passes(rail: SchemaEnforcementRail) -> None:
    # Deliberate design choice: duplicate citations are allowed.
    # The model may cite the same chunk for different claims.
    payload = json.dumps(
        {
            "answer": "Revenue $94.9B. iPhone drove $46B.",
            "citations": [
                {"chunk_id": "chunk-1", "quote": "Revenue $94.9B"},
                {"chunk_id": "chunk-1", "quote": "iPhone $46B"},
            ],
            "confidence": "high",
        }
    )
    decision = rail.check(payload, RETRIEVED)
    assert decision.outcome == "pass"
