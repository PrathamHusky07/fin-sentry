"""
Smoke test: FaithfulnessRail against real Gemini.

Runs two synthetic (answer, chunks) pairs:
  - Pair A: answer directly restates a chunk. Expected: score >= 0.7.
  - Pair B: answer asserts something not in chunks. Expected: score < 0.7.

Usage: .venv/bin/python3 scripts/smoke_test_gemini_faithfulness.py
Requires: GEMINI_API_KEY in .env or environment.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Ensure the project root is on sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from finsentry.rails.output.faithfulness import FaithfulnessRail  # noqa: E402


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
    supported = details.get("supported_claims", [])
    unsupported = details.get("unsupported_claims", [])

    print(f"\n--- {label} ---")
    print(f"  Model:             {rail._model_name}")
    print(f"  Status:            {status}")
    print(f"  Score:             {score}")
    print(f"  Latency:           {elapsed_ms} ms")
    print(f"  Gemini calls:      {calls}")
    print(f"  Input tokens:      {in_tok}")
    print(f"  Output tokens:     {out_tok}")
    print(f"  Supported claims:  {supported}")
    print(f"  Unsupported:       {unsupported}")

    if expected_pass:
        passed = decision.outcome == "pass"
        print(f"  Assertion (score >= 0.7): {'PASS' if passed else 'FAIL'}")
    else:
        passed = decision.outcome == "block"
        print(f"  Assertion (score < 0.7): {'PASS' if passed else 'FAIL'}")

    return passed, {"calls": calls, "in_tok": in_tok, "out_tok": out_tok}


async def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Add it to .env or environment.")
        sys.exit(1)

    model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    print(f"Using model: {model}")

    rail = FaithfulnessRail(api_key=api_key, model_name=model, threshold=0.7)

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
        "Pair A (faithful — should PASS)", rail, answer_a, [chunk_a], expected_pass=True
    )
    result_b, usage_b = await run_pair(
        "Pair B (unfaithful — should BLOCK)", rail, answer_b, [chunk_b], expected_pass=False
    )

    total_calls = int(usage_a["calls"]) + int(usage_b["calls"])
    total_in = int(usage_a["in_tok"]) + int(usage_b["in_tok"])
    total_out = int(usage_a["out_tok"]) + int(usage_b["out_tok"])

    print("\n=== TOTAL USAGE ===")
    print(f"  Total Gemini calls:  {total_calls}")
    print(f"  Total input tokens:  {total_in}")
    print(f"  Total output tokens: {total_out}")
    cost_input = total_in / 1_000_000 * 0.30
    cost_output = total_out / 1_000_000 * 2.50
    print(f"  Estimated cost:      ${cost_input + cost_output:.6f} USD")
    print(f"  (input ${cost_input:.6f} + output ${cost_output:.6f})")

    both_pass = result_a and result_b
    print(f"\nOverall: {'ALL ASSERTIONS PASS' if both_pass else 'SOME ASSERTIONS FAILED'}")
    if not both_pass:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
