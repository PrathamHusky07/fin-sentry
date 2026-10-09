"""Tests for scripts/day11_flash_pilot.py. None of them touches the network or a model: they
check the row selection, the pricing and the guards that keep the pilot under its sub-cap."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from day11_flash_pilot import (  # noqa: E402, I001
    SUB_CAP_USD,
    SkipError,
    SpendGuard,
    guarded,
    parse_claims,
    plan_stage2,
    replaying,
    select_rows,
    verification_estimate,
)

from finsentry.frontier.sampling import should_sample_for_frontier  # noqa: E402


def _scored(n: int = 200) -> dict[str, dict[str, object]]:
    return {
        f"row{i:03d}": {
            "split": "holdout" if i % 2 else "calibration",
            "gold_is_hallucination": i % 3 == 0,
        }
        for i in range(n)
    }


def test_rows_are_the_holdout_ids_the_platform_rule_selects() -> None:
    scored = _scored()
    chosen = select_rows(scored)
    assert chosen and all(scored[i]["split"] == "holdout" for i in chosen)
    assert all(should_sample_for_frontier(i, 10) for i in chosen)
    assert chosen == sorted(chosen)


def test_the_selection_cannot_depend_on_a_label() -> None:
    scored = _scored()
    flipped = {
        i: {**v, "gold_is_hallucination": not v["gold_is_hallucination"]} for i, v in scored.items()
    }
    assert select_rows(scored) == select_rows(flipped)
    stripped = {i: {"split": v["split"]} for i, v in scored.items()}
    assert select_rows(stripped) == select_rows(scored)


async def _live(prompt: str) -> tuple[str, int, int, int]:
    return "[]", 100, 10, 50


async def test_the_guard_refuses_a_call_the_cap_does_not_admit() -> None:
    guard = SpendGuard(cap_usd=0.01)
    gen = guarded(_live, guard, "r1", "extract", 0.0099)
    await gen("p")
    assert len(guard.calls) == 1
    with pytest.raises(SkipError):
        await gen("p")  # 0.0003 spent plus the 0.0099 estimate passes 0.01
    assert len(guard.calls) == 1, "a refused call is not made and not recorded"


async def test_the_guard_records_the_real_usage_and_cost_of_each_call() -> None:
    guard = SpendGuard()
    await guarded(_live, guard, "r1", "extract", 0.001)("p")
    call = guard.calls[0]
    assert (call["row"], call["stage"], call["input_tokens"]) == ("r1", "extract", 100)
    assert guard.spent == pytest.approx(100 / 1e6 * 0.75 + (10 + 50) / 1e6 * 3.75)


async def test_a_replayed_prompt_costs_nothing_and_any_other_prompt_goes_live() -> None:
    guard = SpendGuard()
    live = guarded(_live, guard, "r1", "verify", 0.001)
    gen = replaying({"extract prompt": ('["a claim"]', 90, 20, 100)}, live)
    assert (await gen("extract prompt"))[0] == '["a claim"]'
    assert guard.calls == []
    await gen("verify prompt")
    assert len(guard.calls) == 1


def test_claims_parse_the_way_the_judge_reads_them() -> None:
    assert parse_claims('["a", "b"]') == ["a", "b"]
    assert parse_claims('```json\n["a"]\n```') == ["a"]
    assert parse_claims("[]") == []
    assert parse_claims("not json") is None
    assert parse_claims('{"claims": []}') is None
    assert len(parse_claims(str([f"c{i}" for i in range(15)]).replace("'", '"')) or []) == 10


def test_stage_two_is_priced_from_the_exact_claim_counts_and_stops_over_the_cap() -> None:
    contexts = {"a": "x" * 4000, "b": "x" * 4000}
    per_call = verification_estimate(contexts["a"], 44, 249)
    fits = plan_stage2(0.014, {"a": 1, "b": 1}, contexts, 44, 249)
    assert fits.proceed and fits.verification_calls == 2
    assert fits.projected_usd == pytest.approx(2 * per_call, abs=1e-5)
    over = plan_stage2(0.014, {"a": 15, "b": 15}, contexts, 44, 249)
    assert not over.proceed and over.reason == "exceeds_sub_cap"
    assert over.total_if_run_usd > SUB_CAP_USD


def test_zero_claims_means_no_verification_calls_and_always_fits() -> None:
    plan = plan_stage2(0.014, {"a": 0}, {"a": "x" * 4000}, 44, 249)
    assert plan.proceed and plan.verification_calls == 0 and plan.projected_usd == 0.0
