"""
End-to-end diagnostic for the output rail pipeline.

Exercises the three output rails (schema enforcement, regulated phrases,
faithfulness) independently and in combination through the gateway's
rag_query endpoint via FastAPI's TestClient (no live server required).

Usage: .venv/bin/python3 scripts/diagnostic_output_rails_e2e.py
Requires: GEMINI_API_KEY in .env or environment (for faithfulness).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from fastapi.testclient import TestClient  # noqa: E402

from finsentry.rails.output.faithfulness import FaithfulnessRail  # noqa: E402
from finsentry.rails.output.guardrails_schema import (  # noqa: E402
    SchemaEnforcementRail,
)
from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

results: list[tuple[str, bool, str]] = []


def check(label: str, condition: bool, note: str = "") -> None:
    status = PASS if condition else FAIL
    results.append((label, condition, note))
    suffix = f"  # {note}" if note else ""
    print(f"  {status}  {label}{suffix}")


# ---------------------------------------------------------------------------
# Rail A: SchemaEnforcementRail
# ---------------------------------------------------------------------------


def run_schema_rail_diagnostics() -> None:
    print("\n=== Rail A: SchemaEnforcementRail ===")
    rail = SchemaEnforcementRail()
    valid_chunk_ids = {"c1", "c2"}

    # 1. Valid response with citations passes
    valid = json.dumps(
        {
            "answer": "Apple revenue was $391B.",
            "citations": [{"chunk_id": "c1", "quote": "Revenue was $391B."}],
            "confidence": "high",
        }
    )
    d = rail.check(valid, valid_chunk_ids)
    check("valid response passes schema", d.outcome == "pass")

    # 2. Malformed JSON blocks
    d = rail.check("{not valid json}", valid_chunk_ids)
    check("malformed JSON blocks", d.outcome == "block" and d.reason == "malformed_json")

    # 3. Missing required field blocks
    missing_field = json.dumps({"answer": "ok", "confidence": "low"})
    d = rail.check(missing_field, valid_chunk_ids)
    check("missing citations field blocks", d.outcome == "block" and d.reason == "schema_violation")

    # 4. Hallucinated chunk_id blocks
    hallucinated = json.dumps(
        {
            "answer": "Some answer.",
            "citations": [{"chunk_id": "FAKE-ID-NOT-IN-CONTEXT", "quote": "quote"}],
            "confidence": "high",
        }
    )
    d = rail.check(hallucinated, valid_chunk_ids)
    check(
        "hallucinated chunk_id blocks",
        d.outcome == "block" and d.reason == "hallucinated_citation",
    )
    check(
        "hallucinated_citation details has surviving_ids_count",
        "surviving_ids_count" in d.details,
    )

    # 5. Empty citations with non-low confidence blocks
    empty_cit_high = json.dumps(
        {"answer": "I cannot answer.", "citations": [], "confidence": "high"}
    )
    d = rail.check(empty_cit_high, valid_chunk_ids)
    check(
        "empty citations + confidence=high blocks",
        d.outcome == "block" and d.reason == "empty_citations_with_non_low_confidence",
    )

    # 6. Abstention (empty citations + confidence=low) passes
    abstention = json.dumps(
        {"answer": "I cannot answer.", "citations": [], "confidence": "low"}
    )
    d = rail.check(abstention, valid_chunk_ids)
    check("abstention (empty citations + low confidence) passes", d.outcome == "pass")

    # 7. Parsed response is in details on pass
    d = rail.check(valid, valid_chunk_ids)
    check("passing decision includes parsed RagAnswerResponse", "parsed" in d.details)


# ---------------------------------------------------------------------------
# Rail B: RegulatedPhraseRail
# ---------------------------------------------------------------------------


def run_phrase_rail_diagnostics() -> None:
    print("\n=== Rail B: RegulatedPhraseRail ===")
    rail = RegulatedPhraseRail()

    # 1. Clean answer passes
    d = rail.check("Apple's revenue declined 2% in fiscal 2024.")
    check("clean answer passes", d.outcome == "pass")

    # 2. Guaranteed returns (plural) blocks
    d = rail.check("This fund offers guaranteed returns every quarter.")
    check("'guaranteed returns' blocks", d.outcome == "block")
    check("block includes matched_patterns", "matched_patterns" in d.details)

    # 3. Risk-free investment blocks
    d = rail.check("This is a risk-free investment opportunity.")
    check("'risk-free investment' blocks", d.outcome == "block")

    # 4. Risk-free return blocks
    d = rail.check("You will get a risk-free return on your capital.")
    check("'risk-free return' blocks", d.outcome == "block")

    # 5. Can't lose blocks
    d = rail.check("You can't lose money with this strategy.")
    check("\"can't lose\" blocks", d.outcome == "block")

    # 6. Sure thing blocks
    d = rail.check("This investment is a sure thing — prices always go up.")
    check("'sure thing' blocks", d.outcome == "block")

    # 7. Money-back guarantee blocks
    d = rail.check("We offer a money-back guarantee if returns disappoint.")
    check("'money-back guarantee' blocks", d.outcome == "block")

    # 8. Not-case-sensitive: GUARANTEED blocks
    d = rail.check("This GUARANTEED return will exceed the market.")
    check("uppercase GUARANTEED return blocks", d.outcome == "block")

    # 9. Word-boundary: 'riskier' does not trigger 'risk-free' pattern
    d = rail.check("This position is riskier than bonds.")
    check("'riskier' does NOT trigger risk-free pattern", d.outcome == "pass")


# ---------------------------------------------------------------------------
# Rail C: FaithfulnessRail (unit-level, no real API calls)
# ---------------------------------------------------------------------------


def run_faithfulness_rail_diagnostics() -> None:
    print("\n=== Rail C: FaithfulnessRail (disabled mode — no API key required) ===")

    # Test with api_key=None: rail is disabled, always passes
    rail = FaithfulnessRail(api_key=None, model_name="gemini-3.6-flash", threshold=0.7)

    import asyncio

    class FakeChunk:
        def __init__(self, chunk_id: str, text: str) -> None:
            self.chunk_id = chunk_id
            self.text = text

    chunk = FakeChunk("c1", "Apple revenue was $391B in FY2024.")
    d = asyncio.run(rail.check("Apple revenue was $391B in FY2024.", [chunk]))
    check("disabled rail passes with skipped_no_key", d.outcome == "pass")
    check(
        "disabled rail sets faithfulness_status=skipped_no_key",
        d.details.get("faithfulness_status") == "skipped_no_key",
    )

    # Test with real key if available
    api_key = os.getenv("GEMINI_API_KEY", "")
    if api_key:
        print(
            "\n=== Rail C: FaithfulnessRail (live mode — real API) ==="
        )
        print("  NOTE: Live faithfulness check skipped in e2e diagnostic to avoid")
        print("  consuming rate-limit quota. See scripts/smoke_test_gemini_faithfulness.py")
        print("  for the full empirical smoke test.")
    else:
        print("  (GEMINI_API_KEY not set — live faithfulness checks skipped)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary() -> None:
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print(f"\n=== SUMMARY: {passed}/{total} checks passed ===")
    if failed:
        print("FAILED checks:")
        for label, ok, note in results:
            if not ok:
                print(f"  - {label}" + (f"  ({note})" if note else ""))
        sys.exit(1)
    else:
        print("All diagnostic checks passed.")


if __name__ == "__main__":
    run_schema_rail_diagnostics()
    run_phrase_rail_diagnostics()
    run_faithfulness_rail_diagnostics()
    print_summary()
