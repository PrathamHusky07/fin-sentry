"""Classification: facts become one of five outcomes. The expectation is judged apart."""

from __future__ import annotations

from finsentry.redteam.classify import Observation, classify
from finsentry.redteam.registry import get_scenario


def _scenario(scenario_id: str):  # type: ignore[no-untyped-def]
    scenario = get_scenario(scenario_id)
    assert scenario is not None
    return scenario


_DI_EVIDENCE: dict[str, object] = {"gateway_status": 403, "gateway_rail": "prompt-guard-2"}


def test_a_block_by_the_expected_layer_is_caught_and_meets_the_expectation() -> None:
    obs = Observation(
        summary="Blocked.",
        evidence=dict(_DI_EVIDENCE),
        defense_acted=True,
        acting_layer="prompt-guard-2",
    )
    result = classify(_scenario("DI-001"), obs)
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_layer == "prompt-guard-2"


def test_a_block_by_a_different_layer_is_caught_but_does_not_meet_the_expectation() -> None:
    obs = Observation(
        summary="Blocked.",
        evidence={"gateway_status": 403, "gateway_rail": "llama-guard-3"},
        defense_acted=True,
        acting_layer="llama-guard-3",
    )
    result = classify(_scenario("DI-001"), obs)
    assert result.outcome == "caught"
    assert result.expectation == "not_met"
    assert "Expected prompt-guard-2 to act, but llama-guard-3 did." in result.reason


def test_an_attack_that_passes_every_defense_is_missed() -> None:
    obs = Observation(summary="Passed.", evidence=dict(_DI_EVIDENCE), attack_passed=True)
    result = classify(_scenario("DI-001"), obs)
    assert (result.outcome, result.expectation) == ("missed", "not_met")
    assert result.acting_layer is None


def test_a_known_gap_that_is_missed_meets_its_expectation() -> None:
    obs = Observation(
        summary="Passed.",
        evidence={"schema_decision": "pass", "payload_verified": True},
        attack_passed=True,
        payload_verified=True,
    )
    result = classify(_scenario("GAP-001"), obs)
    assert (result.outcome, result.expectation) == ("missed", "met")


def test_a_known_gap_that_is_caught_is_flagged_as_possibly_closed() -> None:
    obs = Observation(
        summary="Blocked.",
        evidence={"schema_decision": "block", "payload_verified": True},
        defense_acted=True,
        acting_layer="schema-enforcement",
        payload_verified=True,
    )
    result = classify(_scenario("GAP-001"), obs)
    assert (result.outcome, result.expectation) == ("caught", "not_met")
    assert "known gap" in result.reason


def test_an_unavailable_evaluator_is_never_caught() -> None:
    obs = Observation(
        summary="x",
        evidence=dict(_DI_EVIDENCE),
        defense_acted=True,
        acting_layer="prompt-guard-2",
        unavailable_reason="The input rail service was unavailable.",
    )
    result = classify(_scenario("DI-001"), obs)
    assert (result.outcome, result.expectation) == ("evaluator_unavailable", "not_assessable")
    assert result.acting_layer is None


def test_a_contradiction_reported_by_the_executor_is_inconclusive() -> None:
    obs = Observation(
        summary="x",
        evidence=dict(_DI_EVIDENCE),
        defense_acted=True,
        acting_layer="prompt-guard-2",
        inconclusive_reason="The stored trace names a different rail.",
    )
    assert classify(_scenario("DI-001"), obs).outcome == "inconclusive"


def test_a_block_without_the_required_evidence_is_inconclusive_not_caught() -> None:
    obs = Observation(summary="Blocked.", evidence={}, defense_acted=True, acting_layer="x")
    result = classify(_scenario("DI-001"), obs)
    assert result.outcome == "inconclusive"
    assert "gateway_status, gateway_rail" in result.reason


def test_a_miss_is_not_counted_when_the_payload_lacked_the_property() -> None:
    obs = Observation(
        summary="Passed.",
        evidence={"schema_decision": "pass", "payload_verified": False},
        attack_passed=True,
        payload_verified=False,
    )
    result = classify(_scenario("GAP-001"), obs)
    assert result.outcome == "inconclusive"


def test_no_decision_at_all_is_inconclusive() -> None:
    assert classify(_scenario("DI-001"), Observation(summary="x")).outcome == "inconclusive"


def test_extra_evidence_keys_do_not_break_classification() -> None:
    obs = Observation(
        summary="Blocked.",
        evidence={**_DI_EVIDENCE, "extra": 1},
        defense_acted=True,
        acting_layer="prompt-guard-2",
    )
    assert classify(_scenario("DI-001"), obs).outcome == "caught"


def test_a_retrieval_catch_must_come_from_the_expected_check() -> None:
    obs = Observation(
        summary="Dropped.",
        evidence={"attack_dropped": True, "drop_check": "source-trust", "control_kept": True},
        defense_acted=True,
        acting_layer="retrieval-rail",
        acting_check="source-trust",
    )
    result = classify(_scenario("IND-001"), obs)
    assert (result.outcome, result.expectation) == ("caught", "not_met")
    assert "prompt-guard" in result.reason
