"""
Smoke test: FaithfulnessRail against real Gemini.

Runs two synthetic (answer, chunks) pairs:
  - Pair A: answer directly restates a chunk. Expected: score >= 0.7.
  - Pair B: answer asserts fabricated facts not in the chunk. Expected: score < 0.7.

Usage (Vertex mode):
  GEMINI_MODE=vertex GOOGLE_CLOUD_PROJECT=fin-sentry .venv/bin/python3 \
    scripts/smoke_test_gemini_faithfulness.py

Usage (Developer API mode):
  GEMINI_MODE=developer GEMINI_API_KEY=<key> .venv/bin/python3 \
    scripts/smoke_test_gemini_faithfulness.py

Requires ADC credentials for vertex mode: gcloud auth application-default login.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# Ensure the project root is on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from finsentry.rails.output.faithfulness import FaithfulnessRail, Mode  # noqa: E402


@dataclass
class FakeChunk:
    chunk_id: str
    text: str


async def run_pair(
    label: str,
    rail: FaithfulnessRail,
    answer: str,
    chunks: list[FakeChunk],
    expected_pass: bool,
) -> tuple[bool, dict[str, object]]:
    t0 = time.monotonic()
    decision = await rail.check(answer, chunks)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    details = decision.details
    score = details.get("score", "n/a")
    status = details.get("faithfulness_status", "unknown")
    calls = details.get("gemini_calls", 0)
    in_tok = details.get("input_tokens", 0)
    out_tok = details.get("output_tokens", 0)
    thoughts_tok = details.get("thoughts_tokens", 0)
    supported = details.get("supported_claims", [])
    unsupported = details.get("unsupported_claims", [])
    cost_report = details.get("cost", {})

    print(f"\n--- {label} ---")
    print(f"  Mode:              {rail._mode}")
    print(f"  Model:             {rail._model_name}")
    print(f"  Status:            {status}")
    print(f"  Score:             {score}")
    print(f"  Latency:           {elapsed_ms} ms")
    print(f"  Gemini calls:      {calls}")
    print(f"  Input tokens:      {in_tok}")
    print(f"  Output tokens:     {out_tok}")
    print(f"  Thinking tokens:   {thoughts_tok}")
    print(f"  Supported claims:  {supported}")
    print(f"  Unsupported:       {unsupported}")
    if cost_report:
        print(f"  Cost cumulative through this pair: ${cost_report.get('run_total_usd', 0):.6f} USD")

    if expected_pass:
        passed = decision.outcome == "pass" and isinstance(score, float) and score >= 0.7
        print(f"  Assertion (score >= 0.7): {'PASS' if passed else 'FAIL'}")
    else:
        passed = decision.outcome == "block"
        print(f"  Assertion (score < 0.7): {'PASS' if passed else 'FAIL'}")

    return passed, {
        "calls": calls,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "thoughts_tok": thoughts_tok,
        "cost_report": cost_report,
    }


async def main() -> None:
    mode_str = os.getenv("GEMINI_MODE", "disabled")
    mode = cast(Mode, mode_str)
    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    api_key = os.getenv("GEMINI_API_KEY")

    print(f"Mode:    {mode}")
    if mode == "vertex":
        print(f"Project: {project}")
        print(f"Location: {location}")
    print(f"Model:   {model}")

    if mode == "disabled":
        print("ERROR: GEMINI_MODE=disabled. Set GEMINI_MODE=vertex or GEMINI_MODE=developer.")
        sys.exit(1)

    rail = FaithfulnessRail(
        mode=mode,
        model_name=model,
        project=project,
        location=location,
        api_key=api_key,
        threshold=0.7,
    )

    if not rail._enabled:
        print("ERROR: Rail initialized as disabled. Check GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY.")
        sys.exit(1)

    # Pair A: answer is a direct paraphrase of the chunk content. Should pass.
    chunk_a = FakeChunk(
        chunk_id="aapl-10k-2024-001",
        text=(
            "Apple Inc. reported total net sales of $391.0 billion for fiscal year 2024, "
            "representing a 2% decrease compared to the prior year. iPhone net sales "
            "contributed $201.0 billion, or approximately 51% of total revenue."
        ),
    )
    answer_a = (
        "Apple's total net sales for fiscal year 2024 were $391.0 billion, a 2% year-over-year "
        "decline. iPhone sales accounted for approximately $201 billion, representing about "
        "half of total revenue."
    )

    # Pair B: answer asserts fabricated facts not in the chunk. Should block.
    chunk_b = FakeChunk(
        chunk_id="msft-10k-2024-001",
        text=(
            "Microsoft reported cloud revenue of $135.0 billion in fiscal year 2024. "
            "Azure grew 29% year over year."
        ),
    )
    answer_b = (
        "Microsoft's total revenue reached $350 billion in fiscal year 2024, with the "
        "gaming division contributing $25 billion. The company announced a special dividend "
        "of $5 per share. Net income grew 40% driven by AI services."
    )

    result_a, usage_a = await run_pair(
        "Pair A (faithful — should PASS)", rail, answer_a, [chunk_a], expected_pass=True,
    )
    result_b, usage_b = await run_pair(
        "Pair B (unfaithful — should BLOCK)", rail, answer_b, [chunk_b], expected_pass=False
    )

    total_calls = int(usage_a["calls"]) + int(usage_b["calls"])
    total_in = int(usage_a["in_tok"]) + int(usage_b["in_tok"])
    total_out = int(usage_a["out_tok"]) + int(usage_b["out_tok"])
    total_thoughts = int(usage_a["thoughts_tok"]) + int(usage_b["thoughts_tok"])

    # Full budget report from the shared rail instance
    cost_report = rail._budget.report()
    print("\n=== TOTAL USAGE ===")
    print(f"  Total Gemini calls:     {total_calls}")
    print(f"  Total input tokens:     {total_in}")
    print(f"  Total output tokens:    {total_out}")
    print(f"  Total thinking tokens:  {total_thoughts}")
    print("\n=== COST REPORT (from CostBudget) ===")
    print(f"  run_total_usd:          ${cost_report['run_total_usd']:.6f}")
    print(f"  day_total_usd:          ${cost_report['day_total_usd']:.6f}")
    print(f"  call_count:             {cost_report['call_count']}")
    print(f"  prompt_tokens_total:    {cost_report['prompt_tokens_total']}")
    print(f"  candidates_tokens_total:{cost_report['candidates_tokens_total']}")
    print(f"  thoughts_tokens_total:  {cost_report['thoughts_tokens_total']}")
    print(f"  ceilings:               {cost_report['ceilings']}")

    both_pass = result_a and result_b
    print(f"\nOverall: {'ALL ASSERTIONS PASS' if both_pass else 'SOME ASSERTIONS FAILED'}")
    if not both_pass:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
