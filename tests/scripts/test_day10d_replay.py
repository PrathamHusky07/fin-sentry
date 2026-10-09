"""Tests for scripts/day10d_replay.py: the replay reproduces the committed calibration numbers,
the 10 percent rule is the platform's and never reads a label, and the preflight does not claim
an exact cost it cannot know."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from day10d_replay import (  # noqa: E402, I001
    MIN_CLASS_COUNT,
    SESSION_CAP_USD,
    Row,
    bootstrap_ci,
    build_report,
    discrimination,
    load_rows,
    preflight,
    sampled_ids,
    subset_discrimination,
)

from finsentry.calibration.metrics import average_precision, roc_auc  # noqa: E402
from finsentry.frontier.sampling import should_sample_for_frontier  # noqa: E402

SUMMARY = (
    Path(__file__).parent.parent.parent / "docs/measurements/calibration/calibration_summary.json"
)
PROBE: dict[str, Any] = {
    "per_call_output_tokens": 44,
    "per_call_thought_tokens": 249,
    "labeled_rows": {
        "holdout_context_chars_mean": 4171,
        "benchmark_rows": 1651,
    },
}


def _row(i: int, gold: bool, score: float, cost: float = 0.003) -> Row:
    return {
        "id": f"id-{i}",
        "gold_is_hallucination": gold,
        "detector_score": score,
        "cost_usd": cost,
        "latency_ms": 3000,
        "split": "holdout",
    }


def test_the_replay_reproduces_the_committed_calibration_numbers() -> None:
    summary = json.loads(SUMMARY.read_text())
    rows = load_rows()
    held = discrimination([r for r in rows if r["split"] == "holdout"])
    cal = discrimination([r for r in rows if r["split"] == "calibration"])
    assert held["n"] == 150 and held["positives"] == 22
    assert held["average_precision"] == pytest.approx(
        summary["held_out_split"]["average_precision"], abs=1e-4
    )
    assert held["roc_auc"] == pytest.approx(summary["held_out_split"]["roc_auc"], abs=1e-4)
    assert cal["average_precision"] == pytest.approx(
        summary["calibration_split"]["average_precision"], abs=1e-4
    )
    assert held["distinct_detector_scores"] == 3  # the resolution the control is limited to


def test_the_ten_percent_rule_is_the_platforms_rule_and_ignores_labels() -> None:
    rows = [_row(i, gold=i % 7 == 0, score=1.0) for i in range(400)]
    chosen = sampled_ids(rows)
    assert chosen == sorted(r["id"] for r in rows if should_sample_for_frontier(r["id"], 10))
    flipped = [{**r, "gold_is_hallucination": not r["gold_is_hallucination"]} for r in rows]
    assert sampled_ids(flipped) == chosen  # label-blind
    assert sampled_ids(list(reversed(rows))) == chosen  # order does not matter, so it is fixed
    assert set(sampled_ids(rows, 100)) <= set(chosen)  # the reduced rate is a subset
    assert 0.05 < len(chosen) / len(rows) < 0.15


def test_the_bootstrap_interval_is_deterministic_and_brackets_the_estimate() -> None:
    gold = [True] * 20 + [False] * 80
    scores = [1.0] * 15 + [0.0] * 5 + [0.0] * 70 + [1.0] * 10
    first = bootstrap_ci(gold, scores, roc_auc, resamples=200)
    assert first == bootstrap_ci(gold, scores, roc_auc, resamples=200)
    point = roc_auc(gold, scores)
    assert first is not None and point is not None and first[0] <= point <= first[1]
    ap = bootstrap_ci(gold, scores, average_precision, resamples=200)
    assert ap is not None and ap[0] < ap[1]
    assert bootstrap_ci([True, True], [1.0, 0.0], roc_auc) is None  # one class: undefined


def test_a_subset_with_too_few_in_one_class_withholds_its_metrics() -> None:
    thin = [_row(i, gold=i == 0, score=1.0 if i == 0 else 0.0) for i in range(12)]
    result = subset_discrimination(thin)
    assert result["positives"] == 1 and "withheld" in result["metrics"]
    assert "average_precision" not in result
    enough = [_row(i, gold=i < MIN_CLASS_COUNT, score=1.0 if i % 2 else 0.0) for i in range(40)]
    assert "average_precision" in subset_discrimination(enough)


def test_the_preflight_cannot_fix_the_flash_call_count_and_exceeds_the_cap_at_one_claim() -> None:
    holdout = [_row(i, gold=False, score=0.0, cost=0.00336) for i in range(150)]
    result = preflight(holdout, PROBE, rubric_mean_cost=0.00336)
    assert result["flash_calls_established_exactly"] is False
    assert result["flash_calls_range"] == [150, 1650]
    scenarios = result["flash_faithfulness_on_holdout"]
    assert scenarios["0_claims_per_row"]["fits_within_cap_with_margin"] is True
    assert scenarios["1_claims_per_row"]["fits_within_cap_with_margin"] is False
    assert scenarios["1_claims_per_row"]["calls"] == 300
    projected = [scenarios[f"{k}_claims_per_row"]["projected_usd"] for k in (0, 1, 2, 3, 10)]
    assert projected == sorted(projected)  # more claims never cost less
    variant = result["resolution_variant_lower_bound"]
    assert variant["projected_usd"] == pytest.approx(0.504, abs=1e-3)
    assert variant["fits_within_cap_with_margin"] is False
    assert result["planning_ceiling_usd"] < SESSION_CAP_USD


def test_the_report_makes_no_flash_or_variant_claim_and_no_model_call() -> None:
    report = build_report(
        load_rows(), {**PROBE, "labeled_rows": {"holdout_context_chars_mean": 4171}}
    )
    assert report["gemini_calls_made"] == 0
    replay = report["stage2_replay"]
    assert replay["NOT_EVALUATED_flash_only"].startswith("No flash scores")
    assert replay["judge_resolution"]["variant"].startswith("NOT_EVALUATED")
    assert "NOT ESTABLISHED" in replay["crossover"]
    coverage = report["stage1_inventory"]["coverage_on_the_150_row_frozen_set"]
    assert coverage["flash_tier_faithfulness"].startswith("0/150")
    flash_policy = replay["flash_plus_10_percent_frontier"]
    assert flash_policy["status"].startswith("not evaluated")
    assert "cost" in flash_policy["estimated_full_operating_cost"]
