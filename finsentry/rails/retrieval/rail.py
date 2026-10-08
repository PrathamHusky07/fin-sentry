"""
Retrieval rail: filters and sanitises retrieved chunks before RAG generation.

Three checks per chunk, in order:
  1. Source-trust (deterministic): validates chunk_id, ticker, filing_type,
     filing_date, and source_url against the corpus contract.
  2. Prompt Guard 2 injection check: scores the chunk text with the
     PromptGuard2 86M classifier at the retrieval threshold calibrated
     empirically against a 300-chunk benign sample and 40 adversarial examples.
  3. Presidio PII scan: redacts EMAIL_ADDRESS, US_SSN, CREDIT_CARD, IP_ADDRESS,
     and CRYPTO entities in-place using the SEC-context retrieval policy.

Fail-open per chunk: a chunk that fails any check is dropped from the list.
The request continues with remaining chunks. If all chunks are dropped, the
empty list is returned and the RAG endpoint replies without calling the
downstream LLM.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg

from finsentry.rails.input.pii_redaction import (
    _CONFIDENCE_THRESHOLD,
    _RETRIEVAL_ENTITY_TYPES,
    _RETRIEVAL_OPERATORS,
    _get_analyzer,
    _get_anonymizer,
)
from finsentry.rails.input.prompt_guard import PromptGuard2Rail
from finsentry.rails.retrieval.source_trust import check_chunk

log = logging.getLogger(__name__)

# Threshold chosen from empirical calibration (see build-log Task 2 and
# scripts/diagnostic_prompt_guard_retrieval_threshold.py). No threshold
# meets the >= 95% TPR policy target; this is a measured PromptGuard2 86M
# model limitation, not a calibration failure.
#
# Per-category TPR at the chosen threshold=0.3 (canonical, deterministic
# benign sample via MD5(id||'benign-sample-v1'), 2026-09-10):
#   direct_start:   87.5%   direct_end:  100.0%   direct_middle: 100.0%
#   indirect:       62.5%   obfuscated:   37.5%   aggregate:      77.5%
#   FPR benign:      0.0%   FPR imperative-stress: 0.0%
#
# threshold=0.3 strictly dominates 0.4: identical 0.0% benign FPR, but 0.3
# delivers 2.5% higher aggregate TPR and 12.5% higher indirect TPR.
# Retrieval drops chunks individually, so a false positive costs one chunk,
# not the full response.
_RETRIEVAL_INJECTION_THRESHOLD: float = 0.3

# Module-level singleton for the prompt guard rail.
_prompt_guard: PromptGuard2Rail | None = None


def _get_prompt_guard() -> PromptGuard2Rail:
    global _prompt_guard
    if _prompt_guard is None:
        _prompt_guard = PromptGuard2Rail()
    return _prompt_guard


@dataclass(frozen=True)
class ChunkDrop:
    """One chunk the rail dropped, and the check that dropped it."""

    chunk_id: str
    check: Literal["source-trust", "prompt-guard"]
    detail: str
    malicious_probability: float | None = None


@dataclass(frozen=True)
class ChunkRedaction:
    """One kept chunk whose text had PII entities redacted."""

    chunk_id: str
    entity_types: list[str]


@dataclass
class RetrievalReport:
    """What check_chunks_reported did: the survivors plus every decision it made."""

    kept: list[Any]
    drops: list[ChunkDrop] = field(default_factory=list)
    redactions: list[ChunkRedaction] = field(default_factory=list)


class RetrievalRail:
    """Filter and sanitise retrieved chunks before RAG generation.

    Call check_chunks() with the raw candidate list returned by the vector
    search. Returns a new list with untrusted chunks dropped and PII redacted
    in-place on remaining chunks.

    db_url is the psycopg connection string. check_chunks() opens a new
    per-call connection so concurrent event-loop threads do not share state.
    """

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url

    def check_chunks(self, chunks: list[Any]) -> list[Any]:
        """Filter chunks. Returns a new list with unsafe chunks dropped."""
        return self.check_chunks_reported(chunks).kept

    def check_chunks_reported(self, chunks: list[Any]) -> RetrievalReport:
        """Filter chunks and report each drop and redaction with the check behind it.

        chunks: list of objects with attributes chunk_id, ticker, filing_type,
        filing_date, text, similarity_score, and optionally source_url.
        Mutates chunk.text in-place when Presidio finds entities to redact.

        Opens a short-lived psycopg connection for the source-trust DB lookup;
        closed when this method returns.
        """
        report = RetrievalReport(kept=[])

        with psycopg.connect(self._db_url, autocommit=True) as conn:
            for chunk in chunks:
                chunk_id = str(getattr(chunk, "chunk_id", ""))
                ticker = str(getattr(chunk, "ticker", ""))
                filing_type = str(getattr(chunk, "filing_type", ""))
                filing_date = str(getattr(chunk, "filing_date", ""))
                source_url = str(getattr(chunk, "source_url", ""))
                text = str(getattr(chunk, "text", ""))

                # --- Check 1: source trust ---
                trusted, reason = check_chunk(
                    chunk_id=chunk_id,
                    ticker=ticker,
                    filing_type=filing_type,
                    filing_date=filing_date,
                    source_url=source_url,
                    db_conn=conn,
                )
                if not trusted:
                    log.info(
                        "source-trust DROP chunk_id=%s reason=%s", chunk_id, reason
                    )
                    report.drops.append(ChunkDrop(chunk_id, "source-trust", reason))
                    continue

                # --- Check 2: prompt-guard injection check ---
                pg = _get_prompt_guard()
                decision = pg.check(text, {})
                malicious_prob = float(decision.details.get("malicious_probability", 0.0))
                if malicious_prob >= _RETRIEVAL_INJECTION_THRESHOLD:
                    log.warning(
                        "prompt-guard DROP chunk_id=%s malicious_prob=%.4f threshold=%.2f",
                        chunk_id,
                        malicious_prob,
                        _RETRIEVAL_INJECTION_THRESHOLD,
                    )
                    report.drops.append(
                        ChunkDrop(
                            chunk_id,
                            "prompt-guard",
                            f"malicious probability at or above {_RETRIEVAL_INJECTION_THRESHOLD}",
                            malicious_prob,
                        )
                    )
                    continue

                # --- Check 3: Presidio PII scan (redact in-place) ---
                analyzer = _get_analyzer()
                anonymizer = _get_anonymizer()
                pii_results = analyzer.analyze(
                    text=text,
                    entities=_RETRIEVAL_ENTITY_TYPES,
                    language="en",
                    score_threshold=_CONFIDENCE_THRESHOLD,
                )
                if pii_results:
                    anonymized = anonymizer.anonymize(
                        text=text,
                        analyzer_results=pii_results,
                        operators=_RETRIEVAL_OPERATORS,
                    )
                    redacted_types = sorted({r.entity_type for r in pii_results})
                    log.info(
                        "presidio REDACT chunk_id=%s entity_types=%s",
                        chunk_id,
                        redacted_types,
                    )
                    chunk.text = anonymized.text
                    report.redactions.append(ChunkRedaction(chunk_id, redacted_types))

                report.kept.append(chunk)

        return report
