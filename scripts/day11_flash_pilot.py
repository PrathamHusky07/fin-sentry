#!/usr/bin/env python3
"""Day 11.0 bounded flash pilot: how many claims does flash faithfulness extract per row, and
what does a row cost? It exists to price the Day 10D comparison, not to make it.

Rows: the frozen held-out FinQA split, filtered by the platform's own 10 percent frontier
rule (SHA-256 of the id, modulo 10). That is the documented sampling procedure from Day 10D.
It depends on the id alone. The script never reads a label, and the Postgres query below
selects only id, context and response.

Spend is staged so the call count is exact before each paid step, with a hard $0.06 sub-cap
of the session cap:

    stage 0  preflight, no network. Prices the extraction calls. Stops if they exceed the cap.
    stage 1  one claim-extraction call per row (exact count). Records claims per row.
    stage 2  an exact verification-call count is now known. Priced from stage 1's measured
             tokens. Stops if spent plus projected exceeds the cap. Otherwise runs the real
             evaluate_faithfulness per row, replaying stage 1's extraction instead of paying
             for it twice.

    python scripts/day11_flash_pilot.py --preflight-only   # no Gemini call
    python scripts/day11_flash_pilot.py                    # the pilot

Vertex mode with Application Default Credentials only, the same path as the deployed judge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finsentry.frontier.sampling import (  # noqa: E402
    NORMAL_DENOMINATOR,
    should_sample_for_frontier,
)
from finsentry.judges.metrics.faithfulness_core import (  # noqa: E402
    CLAIM_EXTRACTION_PROMPT,
    CLAIM_VERIFICATION_PROMPT,
    GenerateFn,
    _strip_json_fences,
    evaluate_faithfulness,
    make_gemini_generate_fn,
)
from finsentry.judges.metrics.faithfulness_core import _SkipError as SkipError  # noqa: E402
from finsentry.rails.output.cost_governance import CostBudget  # noqa: E402

SUB_CAP_USD = 0.06
CHARS_PER_TOKEN = 3.5  # assumption for the preflight, not a measurement
MAX_CLAIMS = 10
RECORDS = ROOT / "docs/measurements/calibration/finqa_judge_outputs.json"
PROBE = ROOT / "docs/measurements/cost-accuracy/day10d-flash-cost-probe.json"
OUTPUT = ROOT / "docs/measurements/cost-accuracy/day11-flash-pilot.json"


def select_rows(
    scored: dict[str, dict[str, Any]], denominator: int = NORMAL_DENOMINATOR
) -> list[str]:
    """Held-out ids the 1-in-`denominator` rule selects. Reads each record's split and nothing
    else, so a label cannot influence which rows run."""
    holdout = sorted(i for i, v in scored.items() if v["split"] == "holdout")
    return [i for i in holdout if should_sample_for_frontier(i, denominator)]


def token_estimate(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def call_cost(in_tokens: int, out_tokens: int, thought_tokens: int) -> float:
    return CostBudget.estimate_call_cost(in_tokens, out_tokens, thought_tokens)


def extraction_estimate(answer: str, out_tokens: int, thought_tokens: int) -> float:
    prompt_chars = len(CLAIM_EXTRACTION_PROMPT) + len(answer)
    return call_cost(token_estimate(prompt_chars), out_tokens, thought_tokens)


def verification_estimate(context: str, out_tokens: int, thought_tokens: int) -> float:
    # The claim text is short next to the context, so 200 characters stands in for it.
    chars = len(CLAIM_VERIFICATION_PROMPT) + len(context) + 200
    return call_cost(token_estimate(chars), out_tokens, thought_tokens)


@dataclass
class SpendGuard:
    """The authority on real spend. Every real call is checked against the cap before it is
    made and recorded after, so the total cannot pass the cap by more than one call's error."""

    cap_usd: float = SUB_CAP_USD
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def spent(self) -> float:
        return sum(c["cost_usd"] for c in self.calls)

    def admits(self, projected_usd: float) -> bool:
        return self.spent + projected_usd <= self.cap_usd

    def record(self, row_id: str, stage: str, usage: tuple[int, int, int], latency_ms: int) -> None:
        in_tok, out_tok, thought_tok = usage
        self.calls.append(
            {
                "row": row_id,
                "stage": stage,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "thought_tokens": thought_tok,
                "cost_usd": call_cost(in_tok, out_tok, thought_tok),
                "latency_ms": latency_ms,
            }
        )


def guarded(
    live: GenerateFn, guard: SpendGuard, row_id: str, stage: str, estimate: float
) -> GenerateFn:
    """A GenerateFn that refuses a call the cap does not admit and records every real one."""

    async def generate(prompt: str) -> tuple[str, int, int, int]:
        if not guard.admits(estimate):
            raise SkipError("skipped_budget", {"ceiling": "pilot_sub_cap"})
        started = time.monotonic()
        text, in_tok, out_tok, thought_tok = await live(prompt)
        guard.record(
            row_id,
            stage,
            (in_tok, out_tok, thought_tok),
            round((time.monotonic() - started) * 1000),
        )
        return text, in_tok, out_tok, thought_tok

    return generate


def replaying(cached: dict[str, tuple[str, int, int, int]], live: GenerateFn) -> GenerateFn:
    """Return a stored response for a prompt already paid for, and call `live` for the rest."""

    async def generate(prompt: str) -> tuple[str, int, int, int]:
        return cached[prompt] if prompt in cached else await live(prompt)

    return generate


def parse_claims(text: str) -> list[str] | None:
    """The claim list exactly as evaluate_faithfulness reads it, or None when unparseable."""
    try:
        parsed = json.loads(_strip_json_fences(text))
    except (json.JSONDecodeError, ValueError):
        return None
    return [str(c) for c in parsed][:MAX_CLAIMS] if isinstance(parsed, list) else None


@dataclass(frozen=True)
class Stage2Plan:
    proceed: bool
    verification_calls: int
    projected_usd: float
    total_if_run_usd: float
    reason: str


def plan_stage2(
    spent: float,
    claims_per_row: dict[str, int],
    contexts: dict[str, str],
    out_tokens: int,
    thought_tokens: int,
    cap: float = SUB_CAP_USD,
) -> Stage2Plan:
    """Price the exact verification calls the stage 1 claim counts imply."""
    calls = sum(claims_per_row.values())
    projected = sum(
        n * verification_estimate(contexts[r], out_tokens, thought_tokens)
        for r, n in claims_per_row.items()
    )
    total = spent + projected
    if total > cap:
        return Stage2Plan(False, calls, round(projected, 5), round(total, 5), "exceeds_sub_cap")
    return Stage2Plan(True, calls, round(projected, 5), round(total, 5), "fits_sub_cap")


def load_rows(ids: list[str]) -> dict[str, tuple[str, str]]:
    """id -> (context, response). The query names no label column."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("SET default_transaction_read_only = on")
        rows = conn.execute(
            "SELECT id, context, response FROM hallucination_bench WHERE id = ANY(%s)", (ids,)
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def build_preflight(
    ids: list[str], rows: dict[str, tuple[str, str]], probe: dict[str, Any]
) -> dict[str, Any]:
    out_t, thought_t = probe["per_call_output_tokens"], probe["per_call_thought_tokens"]
    extract = {i: extraction_estimate(rows[i][1], out_t, thought_t) for i in ids}
    verify = {i: verification_estimate(rows[i][0], out_t, thought_t) for i in ids}
    stage0 = sum(extract.values())
    return {
        "sub_cap_usd": SUB_CAP_USD,
        "rows": len(ids),
        "row_ids": ids,
        "selection": "held-out split filtered by should_sample_for_frontier(id, 10); no label read",
        "stage1_extraction_calls": len(ids),
        "stage1_projected_usd": round(stage0, 5),
        "stage1_fits_sub_cap": stage0 <= SUB_CAP_USD,
        "estimate_basis": {
            "output_tokens_per_call": out_t,
            "thought_tokens_per_call": thought_t,
            "from": "Day 10D live-judge probe, a different workload",
            "chars_per_token_assumption": CHARS_PER_TOKEN,
            "mean_extraction_call_usd": round(statistics.mean(extract.values()), 5),
            "mean_verification_call_usd": round(statistics.mean(verify.values()), 5),
        },
        "stage2_note": "the verification call count is the sum of stage 1 claim counts, known "
        "only after stage 1, and is priced before any verification call",
        "verification_calls_if_claims_per_row": {
            str(k): {
                "calls": len(ids) * k,
                "total_projected_usd": round(stage0 + sum(k * verify[i] for i in ids), 4),
                "fits_sub_cap": stage0 + sum(k * verify[i] for i in ids) <= SUB_CAP_USD,
            }
            for k in (1, 2, 3)
        },
    }


def make_live() -> GenerateFn:
    """Vertex with ADC, the deployed judge's path. Anything else is refused: no API key."""
    if os.getenv("GEMINI_MODE") != "vertex":
        raise SystemExit("GEMINI_MODE must be vertex. This pilot never uses an API key.")
    if os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is set. Unset it so no key route can be used.")
    from google import genai

    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )
    return make_gemini_generate_fn(client, os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))


async def run_pilot(
    ids: list[str],
    rows: dict[str, tuple[str, str]],
    preflight: dict[str, Any],
    live: GenerateFn,
    guard: SpendGuard,
) -> dict[str, Any]:
    out_t, thought_t = (
        preflight["estimate_basis"]["output_tokens_per_call"],
        preflight["estimate_basis"]["thought_tokens_per_call"],
    )
    cached: dict[str, dict[str, tuple[str, int, int, int]]] = {}
    claims: dict[str, list[str] | None] = {}
    stage1_stop: str | None = None

    for row_id in ids:
        answer = rows[row_id][1]
        prompt = CLAIM_EXTRACTION_PROMPT.format(answer=answer)
        gen = guarded(live, guard, row_id, "extract", extraction_estimate(answer, out_t, thought_t))
        try:
            result = await gen(prompt)
        except SkipError as exc:
            stage1_stop = f"{row_id}: {exc.status}"
            break
        cached[row_id] = {prompt: result}
        claims[row_id] = parse_claims(result[0])

    measured = [c for c in guard.calls if c["stage"] == "extract"]
    obs_out = round(statistics.mean(c["output_tokens"] for c in measured)) if measured else out_t
    obs_thought = (
        round(statistics.mean(c["thought_tokens"] for c in measured)) if measured else thought_t
    )
    counts = {r: len(c) for r, c in claims.items() if c is not None}
    plan = plan_stage2(guard.spent, counts, {r: rows[r][0] for r in counts}, obs_out, obs_thought)
    report: dict[str, Any] = {
        "stage1": {
            "extraction_calls": len(measured),
            "stopped": stage1_stop,
            "claims_per_row": counts,
            "unparseable_rows": sorted(r for r, c in claims.items() if c is None),
            "claims_total": sum(counts.values()),
            "claims_per_row_mean": round(statistics.mean(counts.values()), 3) if counts else None,
            "spent_usd": round(guard.spent, 6),
        },
        "stage2_preflight": {
            "verification_calls": plan.verification_calls,
            "projected_usd": plan.projected_usd,
            "total_if_run_usd": plan.total_if_run_usd,
            "decision": "run" if plan.proceed and not stage1_stop else f"stop: {plan.reason}",
            "priced_from": {
                "output_tokens_per_call": obs_out,
                "thought_tokens_per_call": obs_thought,
            },
        },
    }
    scores: dict[str, Any] = {}
    if plan.proceed and not stage1_stop:
        for row_id in counts:
            if not counts[row_id]:
                scores[row_id] = {"score": 1.0, "claims": 0, "note": "no claims extracted"}
                continue
            est = verification_estimate(rows[row_id][0], obs_out, obs_thought)
            gen = replaying(cached[row_id], guarded(live, guard, row_id, "verify", est))
            res = await evaluate_faithfulness(rows[row_id][1], [rows[row_id][0]], gen, CostBudget())
            scores[row_id] = {"score": res.score, "claims": counts[row_id], "status": res.status}
    report["stage2"] = scores

    per_row: dict[str, float] = {}
    for c in guard.calls:
        per_row[c["row"]] = per_row.get(c["row"], 0.0) + c["cost_usd"]
    latencies = [c["latency_ms"] for c in guard.calls]
    report["totals"] = {
        "real_gemini_calls": len(guard.calls),
        "calls_by_stage": {
            s: sum(1 for c in guard.calls if c["stage"] == s) for s in ("extract", "verify")
        },
        "input_tokens": sum(c["input_tokens"] for c in guard.calls),
        "output_tokens": sum(c["output_tokens"] for c in guard.calls),
        "thought_tokens": sum(c["thought_tokens"] for c in guard.calls),
        "estimated_cost_usd": round(guard.spent, 6),
        "sub_cap_usd": SUB_CAP_USD,
        "within_sub_cap": guard.spent <= SUB_CAP_USD,
        "cost_per_row_usd_mean": round(statistics.mean(per_row.values()), 6) if per_row else None,
        "latency_ms_mean": round(statistics.mean(latencies)) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "cost_basis": "usage-metadata estimate at the Vertex standard-tier constants, not billing",
    }
    report["calls"] = guard.calls
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--preflight-only", action="store_true", help="price the pilot, call nothing"
    )
    args = parser.parse_args()

    ids = select_rows(json.loads(RECORDS.read_text()))
    rows = load_rows(ids)
    ids = [i for i in ids if i in rows]
    preflight = build_preflight(ids, rows, json.loads(PROBE.read_text()))
    result: dict[str, Any] = {
        "purpose": "price the flash-vs-frontier comparison by measuring claims per row; the "
        "comparison itself is not made",
        "labels_read": False,
        "preflight": preflight,
    }
    print(json.dumps(preflight, indent=2))
    if not preflight["stage1_fits_sub_cap"]:
        result["outcome"] = (
            "stopped at preflight: extraction alone exceeds the sub-cap, no call made"
        )
    elif args.preflight_only:
        result["outcome"] = "preflight only, no call made"
    else:
        OUTPUT.write_text(
            json.dumps({**result, "outcome": "preflight written, calls starting"}, indent=2)
        )
        guard = SpendGuard()
        try:
            result.update(asyncio.run(run_pilot(ids, rows, preflight, make_live(), guard)))
            result["outcome"] = "pilot ran"
        except BaseException as exc:
            # Real spend is recorded even when the run is cut short.
            result["outcome"] = f"interrupted: {type(exc).__name__}: {exc}"
            result["calls"] = guard.calls
            result["spent_usd"] = round(guard.spent, 6)
            OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
            raise
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print("outcome:", result["outcome"])


if __name__ == "__main__":
    main()
