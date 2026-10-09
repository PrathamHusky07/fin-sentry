"""output_rails executor against the real schema and phrase rails; faithfulness is a fake."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from finsentry.rails.base import RailDecision
from finsentry.rails.output.guardrails_schema import SchemaEnforcementRail
from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail
from finsentry.redteam.classify import classify
from finsentry.redteam.exec_output import run_output_rails, verify_payload
from tests.redteam.helpers import make_deps, scenario


async def _run(scenario_id: str, faithfulness: object | None = None, **deps: object):  # type: ignore[no-untyped-def]
    s = scenario(scenario_id)
    all_deps = make_deps(
        schema_rail=SchemaEnforcementRail(),
        phrase_rail=RegulatedPhraseRail(),
        faithfulness_rail=faithfulness,
        **deps,
    )
    obs = await run_output_rails(s, all_deps)  # type: ignore[arg-type]
    return obs, classify(s, obs)


def _faithfulness(outcome: str, status: str, reason: str = "r", score: float = 0.2) -> MagicMock:
    rail = MagicMock()
    rail.check = AsyncMock(
        return_value=RailDecision(
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
            details={
                "faithfulness_status": status,
                "score": score,
                "threshold": 0.7,
                "supported_claims": ["a"],
                "unsupported_claims": ["b", "c"],
                "gemini_calls": 4,
                "cost": {"run_total_usd": 0.0123},
            },
        )
    )
    return rail


async def test_a_fabricated_citation_id_is_caught_by_the_schema_rail() -> None:
    obs, result = await _run("OUT-001")
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_layer == "schema-enforcement"
    assert result.acting_check == "hallucinated_citation"
    assert obs.evidence["payload_verified"] is True


async def test_guaranteed_returns_pass_the_schema_rail_and_are_caught_by_the_phrase_rail() -> None:
    obs, result = await _run("OUT-002")
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_layer == "regulated-phrases"
    assert obs.evidence["schema_decision"] == {"outcome": "pass", "reason": "schema valid"}


async def test_the_quote_gap_is_a_verified_miss_that_meets_its_known_gap_expectation() -> None:
    obs, result = await _run("GAP-001")
    assert (result.outcome, result.expectation) == ("missed", "met")
    assert obs.evidence["payload_verified"] is True
    assert "faithfulness_decision" not in obs.evidence


async def test_a_deterministic_scenario_never_calls_the_judge() -> None:
    judge = _faithfulness("block", "blocked")
    await _run("GAP-001", faithfulness=judge)
    judge.check.assert_not_called()


async def test_an_unsupported_claim_blocked_by_the_judge_is_caught_and_records_spend() -> None:
    obs, result = await _run("OUT-003", _faithfulness("block", "blocked", "low_faithfulness"))
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_layer == "faithfulness"
    assert (obs.gemini_calls, obs.cost_usd) == (4, 0.0123)
    assert obs.evidence["faithfulness_decision"]["unsupported_claim_count"] == 2  # type: ignore[index]


async def test_a_judge_that_passes_the_unsupported_answer_is_a_miss() -> None:
    _, result = await _run("OUT-003", _faithfulness("pass", "passed", score=0.9))
    assert (result.outcome, result.expectation) == ("missed", "not_met")


async def test_a_skipped_judge_is_evaluator_unavailable_never_caught() -> None:
    for status in (
        "skipped_rate_limit",
        "skipped_timeout",
        "skipped_upstream_error",
        "skipped_no_key",
    ):
        obs, result = await _run("OUT-003", _faithfulness("pass", status))
        assert result.outcome == "evaluator_unavailable", status
        assert result.acting_layer is None
        assert obs.gemini_calls == 4


async def test_a_missing_faithfulness_rail_is_evaluator_unavailable() -> None:
    _, result = await _run("OUT-003", None)
    assert result.outcome == "evaluator_unavailable"


async def test_missing_output_rails_are_evaluator_unavailable() -> None:
    s = scenario("OUT-001")
    obs = await run_output_rails(s, make_deps())
    assert classify(s, obs).outcome == "evaluator_unavailable"


async def test_a_payload_without_the_property_under_test_is_inconclusive() -> None:
    s = scenario("GAP-001")
    quote_present = s.input.model_copy(  # type: ignore[union-attr]
        update={
            "retrieved": [
                SimpleNamespace(
                    chunk_id="rt-chunk-1",
                    text="Management expects revenue to double in fiscal 2026.",
                )
            ]
        }
    )
    assert verify_payload(quote_present) is False  # type: ignore[arg-type]


def test_verify_payload_checks_each_kind_against_ground_truth() -> None:
    assert verify_payload(scenario("OUT-001").input) is True  # type: ignore[arg-type]
    assert verify_payload(scenario("OUT-002").input) is True  # type: ignore[arg-type]
    assert verify_payload(scenario("OUT-003").input) is True  # type: ignore[arg-type]
    assert verify_payload(scenario("GAP-001").input) is True  # type: ignore[arg-type]
