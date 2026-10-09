#!/usr/bin/env python3
"""Day 10D stages 1 to 3: inventory, offline replay and cost preflight. Zero Gemini calls.

Reads only the checked-in rubric judge outputs from the Day 5 calibration. It computes every
policy result that persisted evidence supports, states the 10 percent sampling rule, and
prices the fresh inference that is missing without making any of it. The flash cost it
cites comes from day10d_probe.py, which reads live data and writes day10d-flash-cost-probe.json.

    python scripts/day10d_probe.py     # read-only, refreshes the probe
    python scripts/day10d_replay.py    # writes docs/measurements/cost-accuracy/day10d-replay.json
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finsentry.calibration.metrics import (  # noqa: E402
    average_precision,
    roc_auc,
    wilson_interval,
)
from finsentry.frontier.sampling import (  # noqa: E402
    NORMAL_DENOMINATOR,
    should_sample_for_frontier,
)
from finsentry.rails.output.cost_governance import CostBudget  # noqa: E402

RECORDS = ROOT / "docs/measurements/calibration/finqa_judge_outputs.json"
OUT_DIR = ROOT / "docs/measurements/cost-accuracy"
REPORT = OUT_DIR / "day10d-replay.json"
PROBE = OUT_DIR / "day10d-flash-cost-probe.json"
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261009
SESSION_CAP_USD = 0.50
MIN_CLASS_COUNT = 5  # below this in either class, AP and AUC are not reported for a subset
SAFETY_MARGIN = 0.20  # a plan must fit in 80 percent of the cap
CHARS_PER_TOKEN = 3.5  # assumption for the preflight, not a measurement
JUDGE_CODE = (
    "finsentry/frontier/adapters/gemini_rubric_adapter.py",
    "finsentry/frontier/prompts/rubric_v2_faithjudge.py",
)

Row = dict[str, Any]


def load_rows() -> list[Row]:
    return list(json.loads(RECORDS.read_text()).values())


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def gold_and_scores(rows: Sequence[Row]) -> tuple[list[bool], list[float]]:
    return [bool(r["gold_is_hallucination"]) for r in rows], [
        float(r["detector_score"]) for r in rows
    ]


def bootstrap_ci(
    gold: list[bool],
    scores: list[float],
    metric: Callable[[list[bool], list[float]], float | None],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """95 percent percentile interval from a class-stratified bootstrap. Each class is
    resampled on its own, so every resample keeps both classes and the same prevalence."""
    pos = [s for g, s in zip(gold, scores, strict=True) if g]
    neg = [s for g, s in zip(gold, scores, strict=True) if not g]
    if not pos or not neg:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        p = rng.choices(pos, k=len(pos))
        n = rng.choices(neg, k=len(neg))
        value = metric([True] * len(p) + [False] * len(n), p + n)
        if value is not None:
            values.append(value)
    return round(percentile(values, 2.5), 4), round(percentile(values, 97.5), 4)


def discrimination(rows: Sequence[Row]) -> dict[str, Any]:
    gold, scores = gold_and_scores(rows)
    positives = sum(gold)
    ap, auc = average_precision(gold, scores), roc_auc(gold, scores)
    by_level = {
        str(level): {
            "hallucination": sum(1 for g, s in zip(gold, scores, strict=True) if g and s == level),
            "faithful": sum(1 for g, s in zip(gold, scores, strict=True) if not g and s == level),
        }
        for level in sorted(set(scores))
    }
    return {
        "n": len(rows),
        "positives": positives,
        "positive_rate": round(positives / len(rows), 4),
        "average_precision": None if ap is None else round(ap, 4),
        "average_precision_ci95": bootstrap_ci(gold, scores, average_precision),
        "roc_auc": None if auc is None else round(auc, 4),
        "roc_auc_ci95": bootstrap_ci(gold, scores, roc_auc),
        "distinct_detector_scores": len(by_level),
        "detector_score_by_gold_label": by_level,
    }


def subset_discrimination(rows: Sequence[Row]) -> dict[str, Any]:
    """`discrimination`, or the counts alone when a class is too small to support a metric."""
    positives = sum(gold_and_scores(rows)[0])
    if min(positives, len(rows) - positives) < MIN_CLASS_COUNT:
        return {
            "n": len(rows),
            "positives": positives,
            "metrics": f"withheld: fewer than {MIN_CLASS_COUNT} rows in one class",
        }
    return discrimination(rows)


def cost_and_latency(rows: Sequence[Row]) -> dict[str, Any]:
    cost = [float(r["cost_usd"]) for r in rows]
    latency = [float(r["latency_ms"]) for r in rows]
    mean_cost = sum(cost) / len(cost)
    return {
        "recorded_estimated_cost_usd_total": round(sum(cost), 4),
        "recorded_estimated_cost_usd_per_row_mean": round(mean_cost, 5),
        "recorded_estimated_cost_usd_per_1000_requests": round(mean_cost * 1000, 2),
        "latency_ms_mean": round(sum(latency) / len(latency)),
        "latency_ms_p50": percentile(latency, 50),
        "latency_ms_p95": percentile(latency, 95),
        "cost_basis": "usage-metadata estimate at the Vertex standard-tier constants, not billing",
    }


def sampled_ids(rows: Sequence[Row], denominator: int = NORMAL_DENOMINATOR) -> list[str]:
    """The rows a 1-in-`denominator` frontier policy would evaluate. This is the platform's
    own rule (SHA-256 of the id, modulo the denominator), so it never looks at a label."""
    return sorted(r["id"] for r in rows if should_sample_for_frontier(r["id"], denominator))


def flash_call_cost(input_tokens: float, output_tokens: float, thought_tokens: float) -> float:
    return CostBudget.estimate_call_cost(
        round(input_tokens), round(output_tokens), round(thought_tokens)
    )


def preflight(
    holdout: Sequence[Row], probe: dict[str, Any], rubric_mean_cost: float
) -> dict[str, Any]:
    """Price the fresh inference that the replay cannot supply. Nothing here calls a model.

    Flash faithfulness is one claim extraction call plus one verification call per claim, and
    each verification re-sends the whole context. The claim count per row is the unknown, so
    the cost is a range over it and not a number."""
    n = len(holdout)
    context_tokens = probe["labeled_rows"]["holdout_context_chars_mean"] / CHARS_PER_TOKEN
    out_tokens, thought_tokens = probe["per_call_output_tokens"], probe["per_call_thought_tokens"]
    extract = flash_call_cost(90, out_tokens, thought_tokens)
    verify = flash_call_cost(context_tokens + 80, out_tokens, thought_tokens)
    ceiling = SESSION_CAP_USD * (1 - SAFETY_MARGIN)
    scenarios = {
        f"{k}_claims_per_row": {
            "calls": n * (1 + k),
            "projected_usd": round(n * (extract + k * verify), 3),
            "fits_within_cap_with_margin": n * (extract + k * verify) <= ceiling,
        }
        for k in (0, 1, 2, 3, 10)
    }
    variant = round(n * rubric_mean_cost, 3)
    return {
        "cap_usd": SESSION_CAP_USD,
        "planning_ceiling_usd": round(ceiling, 2),
        "estimate_basis": {
            "extraction_call_usd": round(extract, 5),
            "verification_call_usd": round(verify, 5),
            "flash_per_call_tokens_from": "live judge_verdicts probe (a different workload)",
            "context_tokens_per_verification": round(context_tokens),
            "chars_per_token_assumption": CHARS_PER_TOKEN,
        },
        "flash_faithfulness_on_holdout": scenarios,
        "flash_calls_established_exactly": False,
        "flash_calls_range": [n, n * 11],
        "resolution_variant_lower_bound": {
            "calls": n,
            "projected_usd": variant,
            "basis": "holdout rows times the measured mean rubric call cost; a finer score "
            "needs more output tokens, so this is a floor",
            "fits_within_cap_with_margin": variant <= ceiling,
        },
        "frontier_replay_needs_calls": 0,
    }


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


METHOD = {
    "labeled_benchmark": (
        "Cleanlab/FinQA-hallucination-detection, 1651 unique rows, 238 hallucinations"
    ),
    "frozen_evaluation_set": (
        "The 150-row held-out split (seed d5a-m4-finqa-split-v1, 0.7 calibration fraction, "
        "class-stratified) of a 500-row scored subset. FinQA carries the human labels. "
        "FinanceBench is the retrieval corpus and has no hallucination labels."
    ),
    "score_semantics": (
        "faithfulness_score in {0.0, 0.5, 1.0}. detector_score = 1 - faithfulness_score, so a "
        "higher value means more likely a hallucination."
    ),
    "flash_only": "No flash scores exist for the labeled rows. Nothing is extrapolated.",
    "sampling_rule": (
        "should_sample_for_frontier(id, 10): SHA-256 of the row id modulo 10 equals 0. This is "
        "the platform's own rule. It never reads a label, and it depends only on the id, so the "
        "same rows are sampled in every comparison."
    ),
    "combination_rule": (
        "A sampled row takes the frontier detector_score and every other row takes the flash "
        "detector_score. Both are 1 - faithfulness but come from different prompts, so the "
        "mixed ranking is reported only beside the paired flash and frontier scores on the "
        "sampled rows."
    ),
    "reporting_rule": (
        "Report the policy's realized accuracy on its sampled subset and its estimated cost "
        "over all traffic as two separate figures. Never compare the subset against the "
        "full-set flash baseline as if equivalent."
    ),
    "crossover": (
        "NOT ESTABLISHED. It needs three policy points and one cannot be computed. The "
        "literature value of about 20 percent is neither confirmed nor refuted here."
    ),
}


def build_report(rows: list[Row], probe: dict[str, Any]) -> dict[str, Any]:
    holdout = [r for r in rows if r["split"] == "holdout"]
    calibration = [r for r in rows if r["split"] == "calibration"]
    sample = set(sampled_ids(holdout))
    sampled = [r for r in holdout if r["id"] in sample]
    positives = sum(gold_and_scores(sampled)[0])
    rubric_mean = sum(r["cost_usd"] for r in holdout) / len(holdout)
    scored_at = sorted(r["scored_at"] for r in rows)
    hallucinated = [r for r in holdout if r["gold_is_hallucination"]]
    flagged = sum(1 for r in hallucinated if r["detector_score"] > 0)
    return {
        "generated_utc": datetime.now(UTC).isoformat(),
        "git_head": git("rev-parse", "--short", "HEAD"),
        "gemini_calls_made": 0,
        "stage1_inventory": {
            "labeled_benchmark": METHOD["labeled_benchmark"],
            "frozen_evaluation_set": METHOD["frozen_evaluation_set"],
            "persisted_scores": {
                "judge": "gemini-rubric, GeminiRubricAdapter, Vertex gemini-3.6-flash",
                "prompt_version": sorted({r["prompt_version"] for r in rows}),
                "score_semantics": METHOD["score_semantics"],
                "peer_examples": "none (peer_retrieval=None, zero-shot)",
                "rows": len(rows),
                "by_split": {"calibration": len(calibration), "holdout": len(holdout)},
                "status_counts": dict(Counter(r["status"] for r in rows)),
                "scored_utc_range": [scored_at[0], scored_at[-1]],
                "judge_code_last_commit": git(
                    "log", "-1", "--format=%h %ad", "--date=iso", "--", *JUDGE_CODE
                ),
            },
            "coverage_on_the_150_row_frozen_set": {
                "rubric_v2_frontier_judge": f"{len(holdout)}/150 persisted",
                "flash_tier_faithfulness": "0/150: no flash judge score exists for a labeled row",
                "higher_resolution_rubric_variant": "0/150: the variant does not exist yet",
            },
            "label_check": probe["labeled_rows"],
            "incompatible_evidence_not_used": {
                "live_judge_verdicts": "SEC traffic, none of its trace ids is a benchmark id",
                "canary_observations": "30 categorical rubric decisions on ids outside the 500",
            },
        },
        "stage2_replay": {
            "REPLAYED_100_percent_frontier": {
                "heldout_150": {**discrimination(holdout), **cost_and_latency(holdout)},
                "all_scored_500": {**discrimination(rows), **cost_and_latency(rows)},
                "calibration_350": discrimination(calibration),
                "holdout_recall_at_any_nonzero_detector_score": {
                    "flagged": flagged,
                    "hallucinations": len(hallucinated),
                    "wilson95": [round(v, 4) for v in wilson_interval(flagged, len(hallucinated))],
                },
            },
            "NOT_EVALUATED_flash_only": METHOD["flash_only"],
            "flash_plus_10_percent_frontier": {
                "status": "not evaluated: it needs flash scores on every row",
                "sampling_rule": METHOD["sampling_rule"],
                "combination_rule": METHOD["combination_rule"],
                "reporting_rule": METHOD["reporting_rule"],
                "sampled_rows_in_holdout": len(sampled),
                "sampled_rows_that_are_hallucinations": positives,
                "sampled_ids": sorted(sample),
                "REPLAYED_frontier_component_on_sampled_rows": subset_discrimination(sampled),
                "estimated_full_operating_cost": "not computable: it needs the flash cost per row",
            },
            "crossover": METHOD["crossover"],
            "judge_resolution": {
                "control": "frontier_rubric_v2_faithjudge, frozen",
                "control_distinct_scores": discrimination(holdout)["distinct_detector_scores"],
                "variant": "NOT_EVALUATED: not written and not run",
            },
        },
        "stage3_preflight": preflight(holdout, probe, rubric_mean),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(load_rows(), json.loads(PROBE.read_text()))
    REPORT.write_text(json.dumps(report, indent=2))
    print(f"report written to {REPORT}")


if __name__ == "__main__":
    main()
