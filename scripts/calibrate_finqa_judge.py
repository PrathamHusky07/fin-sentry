#!/usr/bin/env python3
"""Day 5 M4 Phase 6-7: run the live Gemini rubric judge against a bounded,
stratified subset of hallucination_bench, persisting results resumably.

Does NOT run all 1,651 rows through Gemini. Selects a deterministic,
stratified calibration/held-out split of the full benchmark (seeded hash
of id, so re-running never reshuffles which rows are calibration-only vs
held-out-only), then a stratified sample within each split bounded by
--cap total Gemini calls (default 150), preserving the benchmark's real
~14.4% positive rate in the sampled subset too.

Idempotent: existing scored rows in the output file are never re-scored.
Stopping this script (Ctrl+C, or the CostBudget guard tripping) and
re-running it later just continues from where it left off.

Run with:
    python scripts/calibrate_finqa_judge.py
    python scripts/calibrate_finqa_judge.py --cap 50   # operator override
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.calibration.split import DEFAULT_SEED, stratified_split, stratified_subsample
from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.prompts.rubric_v2_faithjudge import PROMPT_VERSION
from finsentry.frontier.types import FrontierEvaluationInput
from finsentry.rails.output.cost_governance import CostBudget

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/measurements/calibration/finqa_judge_outputs.json"
)
DEFAULT_CAP = 150
DEFAULT_CALIBRATION_FRACTION = 0.7


def _load_benchmark_rows(database_url: str) -> list[dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT id, question, context, response, is_hallucination FROM hallucination_bench"
        ).fetchall()
    return [
        {
            "id": r[0],
            "question": r[1],
            "context": r[2],
            "response": r[3],
            "is_hallucination": r[4],
        }
        for r in rows
    ]


def _load_existing_outputs() -> dict[str, Any]:
    if OUTPUT_PATH.exists():
        return dict(json.loads(OUTPUT_PATH.read_text()))
    return {}


def _save_outputs(outputs: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(outputs, indent=2, sort_keys=True))


async def _score_one(
    adapter: GeminiRubricAdapter, row: dict[str, Any], budget: CostBudget
) -> dict[str, Any] | None:
    """Returns None when the budget guard blocked this call (adapter
    reports status=unavailable/budget_exhausted) -- caller stops the run."""
    evaluation_input = FrontierEvaluationInput(
        app_trace_id=row["id"],
        question=row["question"],
        answer=row["response"],
        citations=[],
        retrieved_context_chunks=[row["context"]],
        original_rag_event_ts=datetime.now(UTC).isoformat(),
        peer_retrieval=None,
    )
    cost_before = budget.report()["run_total_usd"]
    start = time.monotonic()
    result = await adapter.evaluate(evaluation_input)
    latency_ms = int((time.monotonic() - start) * 1000)
    cost_after = budget.report()["run_total_usd"]

    if result.status == "unavailable" and result.error_detail == "budget_exhausted":
        return None

    return {
        "id": row["id"],
        "gold_is_hallucination": row["is_hallucination"],
        "status": result.status,
        "faithfulness_score": result.faithfulness_score,
        "detector_score": (
            1.0 - result.faithfulness_score if result.faithfulness_score is not None else None
        ),
        "decision": result.decision,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_after - cost_before, 8),
        "error_detail": result.error_detail,
        "scored_at": datetime.now(UTC).isoformat(),
    }


async def _run(cap: int, calibration_fraction: float, seed: str) -> None:
    load_dotenv()
    database_url = os.environ["DATABASE_URL"]

    rows = _load_benchmark_rows(database_url)
    rows_by_id = {r["id"]: r for r in rows}
    ids_by_label: dict[bool, list[str]] = {True: [], False: []}
    for r in rows:
        ids_by_label[r["is_hallucination"]].append(r["id"])
    source_positive_rate = len(ids_by_label[True]) / len(rows)

    split = stratified_split(ids_by_label, seed=seed, calibration_fraction=calibration_fraction)
    cal_cap = round(cap * calibration_fraction)
    holdout_cap = cap - cal_cap

    cal_ids_by_label = {
        label: [i for i in ids if i in split.calibration_ids]
        for label, ids in ids_by_label.items()
    }
    holdout_ids_by_label = {
        label: [i for i in ids if i in split.holdout_ids] for label, ids in ids_by_label.items()
    }
    cal_sample = stratified_subsample(cal_ids_by_label, cal_cap, source_positive_rate, seed)
    holdout_sample = stratified_subsample(
        holdout_ids_by_label, holdout_cap, source_positive_rate, seed
    )

    print(f"Benchmark: {len(rows)} rows, source positive rate {source_positive_rate:.4f}")
    print(
        f"Split: calibration={len(split.calibration_ids)} rows, "
        f"holdout={len(split.holdout_ids)} rows (seed={seed!r})"
    )
    print(
        f"Gemini-call subsample: calibration={len(cal_sample)}/{cal_cap} cap, "
        f"holdout={len(holdout_sample)}/{holdout_cap} cap"
    )

    outputs = _load_existing_outputs()
    already_scored = set(outputs.keys())
    to_score = [
        (row_id, "calibration") for row_id in cal_sample if row_id not in already_scored
    ] + [(row_id, "holdout") for row_id in holdout_sample if row_id not in already_scored]

    print(f"Already scored (resumed): {len(already_scored)}")
    print(f"Remaining to score this run: {len(to_score)}")

    if not to_score:
        print("Nothing left to score.")
        return

    cost_budget = CostBudget()
    adapter = GeminiRubricAdapter(
        cost_budget=cost_budget,
        mode=os.getenv("GEMINI_MODE", "disabled"),
        model_name=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    if not adapter.is_available:
        print("GeminiRubricAdapter not available (check GEMINI_MODE/GOOGLE_CLOUD_PROJECT).")
        return

    scored_this_run = 0
    for row_id, split_name in to_score:
        row = rows_by_id[row_id]
        record = await _score_one(adapter, row, cost_budget)
        if record is None:
            print(f"Budget guard tripped after {scored_this_run} calls this run. Stopping.")
            break
        record["split"] = split_name
        record["prompt_version"] = PROMPT_VERSION
        outputs[row_id] = record
        _save_outputs(outputs)
        scored_this_run += 1
        print(
            f"[{scored_this_run}/{len(to_score)}] {row_id} split={split_name} "
            f"gold={record['gold_is_hallucination']} score={record['faithfulness_score']} "
            f"decision={record['decision']} cost=${record['cost_usd']}"
        )

    report = cost_budget.report()
    print(f"\nScored this run: {scored_this_run}")
    print(f"Total scored so far: {len(outputs)}")
    print(f"Actual Vertex spend this run: ${report['run_total_usd']:.6f}")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--calibration-fraction", type=float, default=DEFAULT_CALIBRATION_FRACTION)
    parser.add_argument("--seed", type=str, default=DEFAULT_SEED)
    args = parser.parse_args()
    asyncio.run(_run(args.cap, args.calibration_fraction, args.seed))
