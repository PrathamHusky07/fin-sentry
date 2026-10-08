"""Scenario registry: the shipped file is valid, and every registry rule rejects what it should."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from finsentry.redteam.models import EVIDENCE_KEYS
from finsentry.redteam.registry import RegistryError, get_scenario, load_scenarios, parse_scenarios

_OUTPUT_SCENARIO: dict[str, Any] = {
    "id": "OUT-900",
    "version": 1,
    "title": "t",
    "category": "output_schema",
    "target_layer": "schema-enforcement",
    "executor": "output_rails",
    "mode": "deterministic",
    "description": "d",
    "input": {
        "raw_output": "{}",
        "retrieved": [{"chunk_id": "c1", "text": "x"}],
        "payload_check": {"kind": "citation_id_unretrieved"},
    },
    "expected": {"outcome": "caught", "layer": "schema-enforcement", "rationale": "r"},
    "required_evidence": ["schema_decision"],
    "severity": "low",
    "severity_rationale": "s",
}


def _variant(**overrides: Any) -> list[dict[str, Any]]:
    scenario = copy.deepcopy(_OUTPUT_SCENARIO)
    scenario.update(overrides)
    return [scenario]


def test_shipped_registry_loads_with_between_eight_and_ten_scenarios() -> None:
    scenarios = load_scenarios()
    assert 8 <= len(scenarios) <= 10
    assert len({s.id for s in scenarios}) == len(scenarios)


def test_shipped_registry_covers_the_required_attack_classes() -> None:
    categories = {s.category for s in load_scenarios()}
    assert {
        "direct_injection",
        "indirect_injection",
        "unsupported_claim",
        "output_schema",
        "regulated_phrase",
        "pii",
        "multi_stage",
    } <= categories


def test_shipped_registry_labels_known_gaps_as_expected_misses() -> None:
    gaps = [s for s in load_scenarios() if s.expected.known_gap]
    assert gaps, "the registry must carry at least one honest known gap"
    assert all(s.expected.outcome == "missed" for s in gaps)
    assert all(s.id.startswith("GAP-") for s in gaps)


def test_only_the_faithfulness_path_is_judge_assisted() -> None:
    judge = [s for s in load_scenarios() if s.mode == "judge_assisted"]
    assert [s.id for s in judge] == ["OUT-003"]
    assert judge[0].target_layer == "faithfulness"


def test_every_required_evidence_key_exists_for_its_executor() -> None:
    for s in load_scenarios():
        assert set(s.required_evidence) <= EVIDENCE_KEYS[s.executor], s.id


def test_get_scenario_returns_none_for_an_unknown_id() -> None:
    assert get_scenario("NOPE-001") is None
    assert get_scenario("DI-001") is not None


def test_a_valid_scenario_parses() -> None:
    assert parse_scenarios(_variant())[0].id == "OUT-900"


def test_duplicate_ids_are_rejected() -> None:
    twice = _variant() + _variant()
    with pytest.raises(RegistryError, match="duplicate"):
        parse_scenarios(twice)


def test_evidence_the_executor_never_emits_is_rejected() -> None:
    with pytest.raises(RegistryError, match="never emits"):
        parse_scenarios(_variant(required_evidence=["gateway_status"]))


def test_a_known_gap_cannot_be_expected_to_be_caught() -> None:
    expected = {
        "outcome": "caught",
        "layer": "schema-enforcement",
        "known_gap": True,
        "rationale": "r",
    }
    with pytest.raises(ValidationError, match="known gap"):
        parse_scenarios(_variant(expected=expected))


def test_an_expected_catch_must_name_a_layer() -> None:
    with pytest.raises(ValidationError, match="name the layer"):
        parse_scenarios(_variant(expected={"outcome": "caught", "rationale": "r"}))


def test_the_expected_layer_must_match_the_target_layer() -> None:
    expected = {"outcome": "caught", "layer": "regulated-phrases", "rationale": "r"}
    with pytest.raises(RegistryError, match="different layer"):
        parse_scenarios(_variant(expected=expected))


def test_judge_assisted_is_limited_to_the_faithfulness_path() -> None:
    with pytest.raises(RegistryError, match="not the faithfulness path"):
        parse_scenarios(_variant(mode="judge_assisted"))


def test_a_retrieval_scenario_needs_an_attack_and_a_control() -> None:
    chunk = {"role": "attack", "borrow_from": {"ticker": "AAPL", "filing_type": "10-K"}}
    scenario = {
        **_OUTPUT_SCENARIO,
        "id": "IND-900",
        "category": "indirect_injection",
        "target_layer": "retrieval-rail",
        "executor": "retrieval_rail",
        "input": {"chunks": [chunk]},
        "expected": {"outcome": "caught", "layer": "retrieval-rail", "rationale": "r"},
        "required_evidence": ["attack_dropped"],
    }
    with pytest.raises(ValidationError, match="attack and one control"):
        parse_scenarios([scenario])


def test_an_unknown_executor_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_scenarios(_variant(executor="shell"))
