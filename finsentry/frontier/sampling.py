"""
Deterministic hash-based 10% sampling for the frontier tier.

Hashing app_trace_id (rather than a random draw) means the same event always
produces the same sampling decision — replaying a RagResponseEvent through
the frontier consumer again (e.g. after a crash and re-delivery) does not
flip whether it gets evaluated, and an operator can check "would this trace
have sampled?" without needing to have observed it live.
"""
from __future__ import annotations

import hashlib

_SAMPLE_RATE_DENOMINATOR = 10


def should_sample_for_frontier(app_trace_id: str) -> bool:
    digest = hashlib.sha256(app_trace_id.encode()).hexdigest()
    return int(digest, 16) % _SAMPLE_RATE_DENOMINATOR == 0


def sampling_key(app_trace_id: str) -> str:
    """The value hashed to produce the sampling decision, carried on the
    verdict event for audit (frontier_sampling_decision_key)."""
    return app_trace_id
