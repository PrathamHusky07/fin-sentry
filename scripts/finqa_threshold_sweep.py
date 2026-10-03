#!/usr/bin/env python3
"""Day 5 M4 Phase 8-9: threshold sweep on the calibration split, final
report on the held-out split only.

Reads docs/measurements/calibration/finqa_judge_outputs.json (written by
scripts/calibrate_finqa_judge.py) and never touches hallucination_bench
or Gemini directly -- this script is pure post-processing over already-
scored rows, free and instant to re-run.

The held-out split is never used to select the threshold: the sweep runs
over calibration rows only, a threshold is chosen by a stated objective,
and that single threshold is then applied once to held-out rows to
produce the final, unbiased report.

Run with:
    python scripts/finqa_threshold_sweep.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.calibration.metrics import (
    ThresholdSweepPoint,
    pr_auc,
    roc_auc,
    select_recall_favoring_threshold,
    sweep_thresholds,
)
from finsentry.calibration.split import DEFAULT_SEED

MEASUREMENTS_DIR = Path(__file__).resolve().parent.parent / "docs/measurements/calibration"
OUTPUTS_PATH = MEASUREMENTS_DIR / "finqa_judge_outputs.json"
SWEEP_PATH = MEASUREMENTS_DIR / "threshold_sweep.json"
SUMMARY_PATH = MEASUREMENTS_DIR / "calibration_summary.json"

THRESHOLD_STEP = 0.05
MIN_PRECISION_FLOOR = 0.2


def _sweep_point_to_dict(p: ThresholdSweepPoint) -> dict[str, object]:
    d = asdict(p)
    d["confusion"] = asdict(p.confusion)
    return d


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
    cal_pr_auc = pr_auc(cal_gold, cal_scores)

    chosen = select_recall_favoring_threshold(sweep_points, min_precision=MIN_PRECISION_FLOOR)

    print(f"Calibration rows scored: {len(cal)} (positive rate {sum(cal_gold)/len(cal_gold):.4f})")
    print(f"Calibration ROC-AUC: {cal_roc_auc}")
    print(f"Calibration PR-AUC: {cal_pr_auc}")
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
        "pr_auc": cal_pr_auc,
        "accuracy_note": (
            "accuracy is shown per point below for completeness only -- at a "
            "~14% positive rate, always predicting faithful (never flagging a "
            "hallucination) already scores ~86% accuracy, so accuracy is not a "
            "headline metric here. PR-AUC is."
        ),
        "sweep": [_sweep_point_to_dict(p) for p in sweep_points],
        "selection_objective": (
            f"recall-favoring: highest recall among thresholds with "
            f"precision >= {MIN_PRECISION_FLOOR} (missing a hallucination is "
            f"assumed costlier than one extra human review)"
        ),
        "selected_threshold": chosen.threshold,
    }
    SWEEP_PATH.write_text(json.dumps(sweep_output, indent=2, sort_keys=True))

    # Phase 9: apply the single selected threshold to held-out rows ONCE.
    holdout_gold = [r["gold_is_hallucination"] for r in holdout]
    holdout_scores = [r["detector_score"] for r in holdout]
    holdout_point = sweep_thresholds(holdout_gold, holdout_scores, [chosen.threshold])[0]
    holdout_roc_auc = roc_auc(holdout_gold, holdout_scores)
    holdout_pr_auc = pr_auc(holdout_gold, holdout_scores)

    holdout_positive_rate = sum(holdout_gold) / len(holdout_gold)
    print(f"\nHeld-out rows scored: {len(holdout)} (positive rate {holdout_positive_rate:.4f})")
    print(f"Held-out ROC-AUC: {holdout_roc_auc}")
    print(f"Held-out PR-AUC: {holdout_pr_auc}")
    print(
        f"Held-out @ threshold={chosen.threshold}: precision={holdout_point.precision:.4f} "
        f"recall={holdout_point.recall:.4f} f1={holdout_point.f1:.4f} "
        f"kappa={holdout_point.kappa:.4f}"
    )
    print(
        f"Held-out confusion: tp={holdout_point.confusion.tp} fp={holdout_point.confusion.fp} "
        f"tn={holdout_point.confusion.tn} fn={holdout_point.confusion.fn}"
    )

    total_cost = sum(r.get("cost_usd", 0.0) for r in json.loads(OUTPUTS_PATH.read_text()).values())
    prompt_versions = {r.get("prompt_version") for r in records if r.get("prompt_version")}

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "Cleanlab/FinQA-hallucination-detection (via hallucination_bench, 1651 rows)",
        "judge": "gemini-rubric (GeminiRubricAdapter, Vertex gemini-3.6-flash)",
        "prompt_version": sorted(prompt_versions),
        "seed": DEFAULT_SEED,
        "subset_size": len(cal) + len(holdout),
        "detector_score_mapping": "detector_score = 1 - faithfulness_score",
        "calibration_split": {
            "n_rows_scored": len(cal),
            "positive_rate": sum(cal_gold) / len(cal_gold),
            "roc_auc": cal_roc_auc,
            "pr_auc": cal_pr_auc,
        },
        "held_out_split": {
            "n_rows_scored": len(holdout),
            "positive_rate": sum(holdout_gold) / len(holdout_gold),
            "roc_auc": holdout_roc_auc,
            "pr_auc": holdout_pr_auc,
            "metrics_at_selected_threshold": _sweep_point_to_dict(holdout_point),
        },
        "selected_threshold": chosen.threshold,
        "selection_objective": sweep_output["selection_objective"],
        "actual_cost_usd": round(total_cost, 6),
        "scope_note": (
            "This calibrates the Gemini rubric judge alone, on a 150-row "
            "stratified subset of the 1651-row benchmark. Full-benchmark "
            "scoring and multi-judge (ensemble) calibration are future work, "
            "not part of this result."
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print(f"\nWrote {SWEEP_PATH}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
