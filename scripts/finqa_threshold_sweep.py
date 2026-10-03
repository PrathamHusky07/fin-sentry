#!/usr/bin/env python3
"""Day 5 M4 Phase 8-9: threshold sweep on the calibration split, final
report on the held-out split only.

Reads docs/measurements/calibration/finqa_judge_outputs.json (written by
scripts/calibrate_finqa_judge.py) and recomputes metrics purely from
already-scored rows -- no Gemini call anywhere in this script, free and
instant to re-run. It does read `hallucination_bench` once, read-only,
to report full-benchmark/full-split provenance counts (how many rows
exist in total vs. how many were actually scored); that is a local
Postgres read, not a Gemini call, and does not affect the metrics below,
which are computed only from the already-scored subset.

The held-out split is never used to select the threshold: the sweep runs
over calibration rows only, a threshold is chosen by a stated objective,
and that single threshold is then applied once to held-out rows to
produce the final, unbiased report.

Run with:
    python scripts/finqa_threshold_sweep.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.calibration.metrics import (
    ThresholdSweepPoint,
    average_precision,
    pr_auc,
    roc_auc,
    select_recall_favoring_threshold,
    sweep_thresholds,
    wilson_interval,
)
from finsentry.calibration.split import (
    DEFAULT_CALIBRATION_FRACTION,
    DEFAULT_SEED,
    stratified_split,
)

MEASUREMENTS_DIR = Path(__file__).resolve().parent.parent / "docs/measurements/calibration"
OUTPUTS_PATH = MEASUREMENTS_DIR / "finqa_judge_outputs.json"
SWEEP_PATH = MEASUREMENTS_DIR / "threshold_sweep.json"
SUMMARY_PATH = MEASUREMENTS_DIR / "calibration_summary.json"

THRESHOLD_STEP = 0.05
MIN_PRECISION_FLOOR = 0.2

METRIC_DEFINITIONS = {
    "primary_pr_metric": "average_precision",
    "secondary_pr_metric": "pr_auc (trapezoidal)",
    "note": (
        "average_precision is the headline PR metric: it folds tied "
        "detector scores into a single step rather than interpolating "
        "across them, so it never reports a precision the judge did not "
        "actually produce at a real threshold. pr_auc (trapezoidal) is "
        "kept only as a secondary diagnostic -- on a quantized score "
        "distribution like this judge's {0.0, 0.5, 1.0}, it is optimistic "
        "because it draws straight lines between tied operating points."
    ),
}


def _sweep_point_to_dict(p: ThresholdSweepPoint) -> dict[str, object]:
    d = asdict(p)
    d["confusion"] = asdict(p.confusion)
    return d


def _class_counts(records: list[dict[str, Any]], label_key: str) -> dict[str, object]:
    n = len(records)
    positives = sum(1 for r in records if r[label_key])
    negatives = n - positives
    return {
        "n": n,
        "positives": positives,
        "negatives": negatives,
        "positive_rate": positives / n if n > 0 else None,
    }


def _score_distribution(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(r["faithfulness_score"] for r in records)
    return {str(score): count for score, count in sorted(counts.items())}


def _load_full_benchmark_labels(database_url: str) -> dict[bool, list[str]]:
    """Read-only, local Postgres read of (id, is_hallucination) for every
    row in the benchmark table -- used only to report provenance counts
    (how large the full benchmark and its full split are), never to
    select a threshold or compute a reported metric."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT id, is_hallucination FROM hallucination_bench").fetchall()
    ids_by_label: dict[bool, list[str]] = {True: [], False: []}
    for row_id, is_hallucination in rows:
        ids_by_label[is_hallucination].append(row_id)
    return ids_by_label


def _build_provenance() -> dict[str, object]:
    load_dotenv()
    ids_by_label = _load_full_benchmark_labels(os.environ["DATABASE_URL"])
    full_n = len(ids_by_label[True]) + len(ids_by_label[False])
    full_positives = len(ids_by_label[True])

    split = stratified_split(
        ids_by_label, seed=DEFAULT_SEED, calibration_fraction=DEFAULT_CALIBRATION_FRACTION
    )
    cal_ids_n = len(split.calibration_ids)
    cal_ids_positives = len(split.calibration_ids & set(ids_by_label[True]))
    holdout_ids_n = len(split.holdout_ids)
    holdout_ids_positives = len(split.holdout_ids & set(ids_by_label[True]))

    def _counts(n: int, positives: int) -> dict[str, object]:
        return {
            "n": n,
            "positives": positives,
            "negatives": n - positives,
            "positive_rate": positives / n if n > 0 else None,
        }

    return {
        "full_benchmark": _counts(full_n, full_positives),
        "full_calibration_split": _counts(cal_ids_n, cal_ids_positives),
        "full_holdout_split": _counts(holdout_ids_n, holdout_ids_positives),
        "split_seed": DEFAULT_SEED,
        "split_calibration_fraction": DEFAULT_CALIBRATION_FRACTION,
        "stratification_note": (
            "Each split and the Gemini-call subsample preserve class "
            "prevalence as closely as integer sample sizes allow (each "
            "class is split/sampled independently, then rounded) -- not "
            "an exact match to the source positive rate."
        ),
    }


def main() -> None:
    records = list(json.loads(OUTPUTS_PATH.read_text()).values())
    scored = [r for r in records if r["status"] == "success" and r["detector_score"] is not None]

    cal = [r for r in scored if r["split"] == "calibration"]
    holdout = [r for r in scored if r["split"] == "holdout"]

    if not cal:
        raise SystemExit("No scored calibration rows -- run scripts/calibrate_finqa_judge.py first")
    if not holdout:
        raise SystemExit("No scored holdout rows -- run scripts/calibrate_finqa_judge.py first")

    cal_gold = [r["gold_is_hallucination"] for r in cal]
    cal_scores = [r["detector_score"] for r in cal]

    thresholds = [round(i * THRESHOLD_STEP, 2) for i in range(int(1 / THRESHOLD_STEP) + 1)]
    sweep_points = sweep_thresholds(cal_gold, cal_scores, thresholds)
    cal_roc_auc = roc_auc(cal_gold, cal_scores)
    cal_ap = average_precision(cal_gold, cal_scores)
    cal_pr_auc = pr_auc(cal_gold, cal_scores)

    chosen = select_recall_favoring_threshold(sweep_points, min_precision=MIN_PRECISION_FLOOR)

    cal_score_dist = _score_distribution(cal)
    holdout_score_dist = _score_distribution(holdout)
    combined_score_dist = _score_distribution(scored)
    distinct_observed_scores = sorted(combined_score_dist.keys())
    regime_collapse_note = (
        "faithfulness_score's API type is a continuous float in [0, 1], "
        f"but across all {len(scored)} scored rows the rubric prompt "
        f"empirically produced only {len(distinct_observed_scores)} "
        f"distinct values: {distinct_observed_scores}. Since "
        "detector_score is a deterministic function of faithfulness_score, "
        f"the {len(thresholds)} swept thresholds ({thresholds[0]}-"
        f"{thresholds[-1]}, step {THRESHOLD_STEP}) collapse to at most "
        f"{len(distinct_observed_scores)} distinct prediction regimes -- "
        "every threshold strictly between two consecutive observed values "
        "produces an identical confusion matrix to its neighbors. "
        "Threshold tuning has limited expressive power until the judge's "
        "score resolution increases beyond this many values."
    )

    print(f"Calibration rows scored: {len(cal)} (positive rate {sum(cal_gold)/len(cal_gold):.4f})")
    print(f"Calibration ROC-AUC: {cal_roc_auc}")
    print(f"Calibration Average Precision (primary): {cal_ap}")
    print(f"Calibration PR-AUC (trapezoidal, secondary): {cal_pr_auc}")
    print(f"Calibration score distribution: {cal_score_dist}")
    print(
        f"Selected threshold: {chosen.threshold} "
        f"(recall-favoring, min_precision floor={MIN_PRECISION_FLOOR}) "
        f"-> precision={chosen.precision:.4f} recall={chosen.recall:.4f} f1={chosen.f1:.4f}"
    )

    sweep_output = {
        "split": "calibration",
        "n_rows": len(cal),
        "positive_rate": sum(cal_gold) / len(cal_gold),
        "threshold_step": THRESHOLD_STEP,
        "roc_auc": cal_roc_auc,
        "average_precision": cal_ap,
        "pr_auc": cal_pr_auc,
        "metric_definitions": METRIC_DEFINITIONS,
        "score_distribution": cal_score_dist,
        "regime_collapse_note": regime_collapse_note,
        "accuracy_note": (
            "accuracy is shown per point below for completeness only -- at a "
            "~14% positive rate, always predicting faithful (never flagging a "
            "hallucination) already scores ~86% accuracy, so accuracy is not a "
            "headline metric here. Average Precision is."
        ),
        "sweep": [_sweep_point_to_dict(p) for p in sweep_points],
        "selection_objective": (
            "Restrict to thresholds with precision >= "
            f"{MIN_PRECISION_FLOOR}; among those pick highest recall, ties "
            "broken by highest F1 then lowest threshold. If none clear the "
            "floor, fall back to the single best-F1 point across all "
            "thresholds (ties broken by lowest threshold). Recall-favoring "
            "because missing a hallucination is assumed costlier than one "
            "extra human review."
        ),
        "selected_threshold": chosen.threshold,
    }
    SWEEP_PATH.write_text(json.dumps(sweep_output, indent=2, sort_keys=True))

    # Phase 9: apply the single selected threshold to held-out rows ONCE.
    holdout_gold = [r["gold_is_hallucination"] for r in holdout]
    holdout_scores = [r["detector_score"] for r in holdout]
    holdout_point = sweep_thresholds(holdout_gold, holdout_scores, [chosen.threshold])[0]
    holdout_roc_auc = roc_auc(holdout_gold, holdout_scores)
    holdout_ap = average_precision(holdout_gold, holdout_scores)
    holdout_pr_auc = pr_auc(holdout_gold, holdout_scores)

    precision_n = holdout_point.confusion.tp + holdout_point.confusion.fp
    precision_ci = wilson_interval(holdout_point.confusion.tp, precision_n)
    recall_n = holdout_point.confusion.tp + holdout_point.confusion.fn
    recall_ci = wilson_interval(holdout_point.confusion.tp, recall_n)

    holdout_positive_rate = sum(holdout_gold) / len(holdout_gold)
    print(f"\nHeld-out rows scored: {len(holdout)} (positive rate {holdout_positive_rate:.4f})")
    print(f"Held-out ROC-AUC: {holdout_roc_auc}")
    print(f"Held-out Average Precision (primary): {holdout_ap}")
    print(f"Held-out PR-AUC (trapezoidal, secondary): {holdout_pr_auc}")
    print(f"Held-out score distribution: {holdout_score_dist}")
    print(
        f"Held-out @ threshold={chosen.threshold}: precision={holdout_point.precision:.4f} "
        f"[{precision_ci[0]:.4f}, {precision_ci[1]:.4f}] n={precision_n}  "
        f"recall={holdout_point.recall:.4f} [{recall_ci[0]:.4f}, {recall_ci[1]:.4f}] "
        f"n={recall_n}  f1={holdout_point.f1:.4f} kappa={holdout_point.kappa:.4f}"
    )
    print(
        f"Held-out confusion: tp={holdout_point.confusion.tp} fp={holdout_point.confusion.fp} "
        f"tn={holdout_point.confusion.tn} fn={holdout_point.confusion.fn}"
    )
    print(f"\n{regime_collapse_note}")

    total_cost = sum(r.get("cost_usd", 0.0) for r in json.loads(OUTPUTS_PATH.read_text()).values())
    prompt_versions = {r.get("prompt_version") for r in records if r.get("prompt_version")}

    provenance = _build_provenance()
    provenance["scored_calibration"] = _class_counts(cal, "gold_is_hallucination")
    provenance["scored_holdout"] = _class_counts(holdout, "gold_is_hallucination")

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "Cleanlab/FinQA-hallucination-detection (via hallucination_bench, 1651 rows)",
        "judge": "gemini-rubric (GeminiRubricAdapter, Vertex gemini-3.6-flash)",
        "prompt_version": sorted(prompt_versions),
        "seed": DEFAULT_SEED,
        "subset_size": len(cal) + len(holdout),
        "detector_score_mapping": "detector_score = 1 - faithfulness_score",
        "metric_definitions": METRIC_DEFINITIONS,
        "provenance": provenance,
        "score_distribution": {
            "calibration": cal_score_dist,
            "holdout": holdout_score_dist,
            "combined": combined_score_dist,
        },
        "regime_collapse_note": regime_collapse_note,
        "calibration_split": {
            "n_rows_scored": len(cal),
            "positive_rate": sum(cal_gold) / len(cal_gold),
            "roc_auc": cal_roc_auc,
            "average_precision": cal_ap,
            "pr_auc": cal_pr_auc,
        },
        "held_out_split": {
            "n_rows_scored": len(holdout),
            "positive_rate": holdout_positive_rate,
            "roc_auc": holdout_roc_auc,
            "average_precision": holdout_ap,
            "pr_auc": holdout_pr_auc,
            "metrics_at_selected_threshold": _sweep_point_to_dict(holdout_point),
            "precision_wilson_ci": {
                "low": precision_ci[0],
                "high": precision_ci[1],
                "n": precision_n,
            },
            "recall_wilson_ci": {
                "low": recall_ci[0],
                "high": recall_ci[1],
                "n": recall_n,
            },
        },
        "selected_threshold": chosen.threshold,
        "selection_objective": sweep_output["selection_objective"],
        "recorded_estimated_cost_usd": round(total_cost, 6),
        "cost_note": (
            "Recorded estimated Vertex cost from usage metadata "
            "(prompt/candidates/thoughts token counts times the Vertex AI "
            "Standard-tier pricing constants in cost_governance.py), not "
            "actual billing spend confirmed against the Google Cloud "
            "billing API."
        ),
        "scope_note": (
            "This calibrates the Gemini rubric judge alone, on a "
            f"{len(cal) + len(holdout)}-row stratified subset of the "
            "1651-row benchmark. Full-benchmark scoring and multi-judge "
            "(ensemble) calibration are future work, not part of this "
            "result."
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print(f"\nWrote {SWEEP_PATH}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
