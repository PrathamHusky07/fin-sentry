#!/usr/bin/env python3
"""Day 10D read-only probe: what the deployed flash judge costs per Gemini call, and the size
and labels of the frozen rows. Reads RisingWave and Postgres. Makes no Gemini call.

    python scripts/day10d_probe.py     # writes day10d-flash-cost-probe.json under cost-accuracy/
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RECORDS = ROOT / "docs/measurements/calibration/finqa_judge_outputs.json"
PROBE = ROOT / "docs/measurements/cost-accuracy/day10d-flash-cost-probe.json"


def probe() -> dict[str, Any]:
    import psycopg
    from dotenv import load_dotenv

    from finsentry.risingwave.dao import risingwave_dsn

    load_dotenv(ROOT / ".env")
    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        row = conn.execute(
            "SELECT count(*), sum(total_gemini_calls), sum(total_input_tokens),"
            " sum(total_output_tokens), sum(total_thoughts_tokens), sum(total_cost_usd)"
            " FROM judge_verdicts WHERE total_gemini_calls > 0"
        ).fetchone()
        live_ids = {
            r[0] for r in conn.execute("SELECT app_trace_id FROM judge_verdicts").fetchall()
        }
    assert row is not None
    verdicts, calls, tokens_in, tokens_out, tokens_thought, cost = (float(x) for x in row)
    scored = json.loads(RECORDS.read_text())
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("SET default_transaction_read_only = on")
        bench = {
            r[0]: r
            for r in conn.execute(
                "SELECT id, context, response, is_hallucination FROM hallucination_bench"
            ).fetchall()
        }
    holdout = [i for i, v in scored.items() if v["split"] == "holdout"]
    return {
        "probed_utc": datetime.now(UTC).isoformat(),
        "source": "RisingWave judge_verdicts (rows with total_gemini_calls > 0) and Postgres "
        "hallucination_bench, both read-only",
        "verdicts": int(verdicts),
        "gemini_calls": int(calls),
        "per_call_input_tokens": round(tokens_in / calls),
        "per_call_output_tokens": round(tokens_out / calls),
        "per_call_thought_tokens": round(tokens_thought / calls),
        "per_call_usd": round(cost / calls, 5),
        "per_verdict_usd_three_ragas_metrics": round(cost / verdicts, 5),
        "per_verdict_calls_three_ragas_metrics": round(calls / verdicts, 2),
        "note": "Three metrics on multi-chunk SEC contexts. Faithfulness alone on FinQA rows "
        "is a different workload, so these are inputs to an estimate and not a measurement of it.",
        "labeled_rows": {
            "benchmark_rows": len(bench),
            "scored_ids_missing_from_benchmark": sum(1 for i in scored if i not in bench),
            "scored_label_mismatches": sum(
                1
                for i, v in scored.items()
                if i in bench and bench[i][3] != v["gold_is_hallucination"]
            ),
            "live_verdict_trace_ids": len(live_ids),
            "live_verdict_ids_that_are_benchmark_ids": len(live_ids & set(bench)),
            "holdout_context_chars_mean": round(
                sum(len(bench[i][1]) for i in holdout) / len(holdout)
            ),
            "holdout_answer_chars_mean": round(
                sum(len(bench[i][2]) for i in holdout) / len(holdout), 1
            ),
        },
    }


if __name__ == "__main__":
    PROBE.parent.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(probe(), indent=2))
    print(f"probe written to {PROBE}")
