"""
Cost governance for Gemini API calls in FaithfulnessRail.

Enforces per-call, per-run, and per-day dollar ceilings so that development and
test runs cannot spend beyond configured limits against the Google Cloud credit.

Pricing: gemini-3.6-flash on Vertex AI Standard tier, effective through Dec 31, 2026.
Thinking tokens are billed at the output rate per Google Cloud Vertex AI pricing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# gemini-3.6-flash Standard pricing through Dec 31, 2026
# (from Google Cloud Vertex AI Agent Platform pricing page)
_INPUT_USD_PER_M_TOKENS = 0.75
_OUTPUT_USD_PER_M_TOKENS = 3.75  # Google bills thinking tokens at output rate

_PER_CALL_CEILING_USD = 0.02
_PER_RUN_CEILING_USD = 5.00
_PER_DAY_CEILING_USD = 25.00


@dataclass
class CallRecord:
    prompt_tokens: int
    candidates_tokens: int
    thoughts_tokens: int
    cost_usd: float
    timestamp: float = field(default_factory=time.monotonic)


class CostBudget:
    """Provides pre-call admission control and exact post-call accounting for Gemini spend.

    Admission control: _estimate_next_call_cost() in FaithfulnessRail projects
    the cost of the next call using the running average of prior calls, and
    can_proceed() gates further calls when that projection plus accumulated spend
    would exceed a configured ceiling.

    Exact accounting: record_call() computes actual cost from usage_metadata
    (prompt_token_count, candidates_token_count, thoughts_token_count) using the
    Vertex AI Standard tier pricing constants above.

    Thinking tokens (thoughts_token_count from Gemini usage_metadata) are billed
    at the output rate per Google Cloud Vertex AI pricing. record_call() takes
    them separately for observability but includes them in output cost calculation.

    Important: this is not a strict per-call reservation. The actual cost of a
    specific upcoming call is unknown before it completes. Under variable token
    usage or concurrent requests against a single rail instance, actual spend may
    briefly exceed the configured per-call ceiling before subsequent calls are
    gated. The invariants guaranteed are: (a) exact post-hoc accounting via
    record_call, (b) admission control that gates further calls once running totals
    cross per-run or per-day ceilings. Suitable for single-process development and
    cost-observability. A stricter reservation mechanism would require broker-side
    or storage-backed reservations, deferred to a future ADR.
    """

    def __init__(
        self,
        per_call_ceiling_usd: float = _PER_CALL_CEILING_USD,
        per_run_ceiling_usd: float = _PER_RUN_CEILING_USD,
        per_day_ceiling_usd: float = _PER_DAY_CEILING_USD,
    ) -> None:
        self._per_call = per_call_ceiling_usd
        self._per_run = per_run_ceiling_usd
        self._per_day = per_day_ceiling_usd
        self._run_total_usd = 0.0
        self._day_total_usd = 0.0  # in-memory; process-restart resets. Fine at Day 3.
        self._records: list[CallRecord] = []

    @staticmethod
    def estimate_call_cost(
        prompt_tokens: int, candidates_tokens: int, thoughts_tokens: int
    ) -> float:
        input_cost = prompt_tokens / 1_000_000 * _INPUT_USD_PER_M_TOKENS
        output_cost = (candidates_tokens + thoughts_tokens) / 1_000_000 * _OUTPUT_USD_PER_M_TOKENS
        return input_cost + output_cost

    def can_proceed(self, projected_call_cost_usd: float = 0.0) -> tuple[bool, str]:
        """Check whether a call can proceed. Returns (allowed, reason)."""
        if projected_call_cost_usd > self._per_call:
            return False, "per_call_ceiling_exceeded"
        if self._run_total_usd + projected_call_cost_usd > self._per_run:
            return False, "per_run_ceiling_exceeded"
        if self._day_total_usd + projected_call_cost_usd > self._per_day:
            return False, "per_day_ceiling_exceeded"
        return True, "ok"

    def record_call(
        self, prompt_tokens: int, candidates_tokens: int, thoughts_tokens: int
    ) -> CallRecord:
        cost = self.estimate_call_cost(prompt_tokens, candidates_tokens, thoughts_tokens)
        record = CallRecord(
            prompt_tokens=prompt_tokens,
            candidates_tokens=candidates_tokens,
            thoughts_tokens=thoughts_tokens,
            cost_usd=cost,
        )
        self._records.append(record)
        self._run_total_usd += cost
        self._day_total_usd += cost
        return record

    def report(self) -> dict[str, Any]:
        return {
            "run_total_usd": round(self._run_total_usd, 6),
            "day_total_usd": round(self._day_total_usd, 6),
            "call_count": len(self._records),
            "prompt_tokens_total": sum(r.prompt_tokens for r in self._records),
            "candidates_tokens_total": sum(r.candidates_tokens for r in self._records),
            "thoughts_tokens_total": sum(r.thoughts_tokens for r in self._records),
            "ceilings": {
                "per_call_usd": self._per_call,
                "per_run_usd": self._per_run,
                "per_day_usd": self._per_day,
            },
        }
