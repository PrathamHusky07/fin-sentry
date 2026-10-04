#!/usr/bin/env python3
"""Day 6 Phase 2 Proof A: a real, bounded (n=30, ~$0.10) live Gemini canary
run against the frozen production DriftConfig policy (window=150, min_n=30,
drift_entry=0.43, recovery=0.54, K=3, M=5, healthy_baseline_kappa=0.6050).

This is a one-shot smoke run, not a scheduler: it scores up to n fresh,
leakage-free hallucination_bench rows (excluding all 500 M4-scored ids)
through the live GeminiRubricAdapter, feeds each result into a fresh
DriftController, and writes the honest resulting classification -- whatever
the real code produces, not a staged outcome -- to
docs/measurements/reliability/canary-live-smoke-d6p2.json.

Run with:
    python scripts/canary_live_smoke_d6p2.py
    python scripts/canary_live_smoke_d6p2.py --n 30   # operator override, default 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.reliability.canary import (
    BenchmarkCanaryScorer,
    _load_m4_scored_ids,
)
from finsentry.reliability.controller import DriftController

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/measurements/reliability/canary-live-smoke-d6p2.json"
)


async def _run(n: int) -> None:
    load_dotenv()
    database_url = os.environ["DATABASE_URL"]

    controller = DriftController()  # frozen production DriftConfig defaults
    scorer = BenchmarkCanaryScorer(database_url=database_url)

    report = await scorer.run_canary_cycle(controller, n=n)

    scored_ids = {o.id for o in report.new_observations}
    m4_ids = _load_m4_scored_ids()
    disjoint = scored_ids.isdisjoint(m4_ids)

    health = report.health_record
    summary = {
        "provenance": asdict(report.provenance),
        "observations": [asdict(o) for o in report.new_observations],
        "health_record": (
            {
                "state": health.state,
                "kappa": health.kappa,
                "window_n": health.window_n,
                "committed_n": health.committed_n,
                "n_abstain": health.n_abstain,
                "n_unavailable": health.n_unavailable,
                "entry_threshold": health.entry_threshold,
                "recovery_threshold": health.recovery_threshold,
            }
            if health is not None
            else None
        ),
        "spend_usd": report.spend_usd,
        "budget_stopped_early": report.budget_stopped_early,
        "disjoint_from_m4_scored_ids": disjoint,
        "scored_id_count": len(scored_ids),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print(f"Eligible pool: {report.provenance.eligible_pool_size}")
    print(f"Excluded M4 ids: {report.provenance.excluded_m4_id_count}")
    print(f"Excluded M4 ids sha256: {report.provenance.excluded_m4_ids_sha256}")
    print(f"Scored this run: {len(report.new_observations)}")
    if health is not None:
        print(
            f"health: state={health.state} kappa={health.kappa} "
            f"window_n={health.window_n} committed_n={health.committed_n} "
            f"n_abstain={health.n_abstain} n_unavailable={health.n_unavailable}"
        )
    print(f"Spend: ${report.spend_usd:.6f}")
    print(f"Budget stopped early: {report.budget_stopped_early}")
    print(f"Disjoint from M4 scored ids: {disjoint}")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(_run(args.n))
