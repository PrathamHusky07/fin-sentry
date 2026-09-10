"""
Presidio SEC-context entity type characterization.

Samples 200 chunks (20 per ticker) and runs Presidio AnalyzerEngine over the
full entity type roster to determine which types fire and how often.

Policy decisions for the retrieval rail are documented inline in the output.

Usage:
    source .venv/bin/activate
    PYTHONPATH=. python scripts/diagnostic_presidio_sec_context.py
"""
from __future__ import annotations

import os
import random
from collections import defaultdict
from typing import Any

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finsentry")

# All entity types Presidio's English recognizers can detect.
ALL_ENTITY_TYPES = [
    "PERSON",
    "LOCATION",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "US_SSN",
    "CREDIT_CARD",
    "DATE_TIME",
    "NRP",
    "IP_ADDRESS",
    "ORGANIZATION",
    "US_DRIVER_LICENSE",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "US_PASSPORT",
    "MEDICAL_LICENSE",
    "URL",
    "CRYPTO",
]


def run() -> None:
    print("=" * 72)
    print("PRESIDIO SEC-CONTEXT ENTITY TYPE CHARACTERIZATION")
    print("=" * 72)

    # --- Sample 200 chunks ---
    print("\nSampling 200 chunks (20 per ticker)...")
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT ticker FROM corpus ORDER BY ticker")
    tickers = [r[0] for r in cur.fetchall()]

    sample_chunks: list[dict[str, Any]] = []
    for ticker in tickers:
        cur.execute("""
            SELECT id, ticker, filing_type, chunk_text
            FROM corpus
            WHERE ticker = %s
            ORDER BY RANDOM()
            LIMIT 20
        """, (ticker,))
        for row in cur.fetchall():
            sample_chunks.append({
                "id": row[0],
                "ticker": row[1],
                "filing_type": row[2],
                "text": row[3],
            })

    cur.close()
    conn.close()
    print(f"  Sample: {len(sample_chunks)} chunks")

    # --- Run Presidio ---
    print("\nInitializing Presidio AnalyzerEngine (all entity types)...")
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.predefined_recognizers import SpacyRecognizer

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()
    analyzer = AnalyzerEngine(registry=registry)
    print("  Presidio ready.")

    print("\nAnalyzing 200 chunks...")
    entity_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for chunk in sample_chunks:
        results = analyzer.analyze(
            text=chunk["text"],
            entities=ALL_ENTITY_TYPES,
            language="en",
        )
        for r in results:
            context_start = max(0, r.start - 30)
            context_end = min(len(chunk["text"]), r.end + 30)
            context = chunk["text"][context_start:context_end].replace("\n", " ")
            entity_hits[r.entity_type].append({
                "ticker": chunk["ticker"],
                "filing_type": chunk["filing_type"],
                "score": r.score,
                "matched": chunk["text"][r.start:r.end],
                "context": context,
            })

    # --- Report: total entity types and counts ---
    print("\n--- Entity Types Fired in Sample ---")
    print(f"\n  {'Entity Type':<25} {'Count':>8}  {'Avg Score':>10}")
    print("  " + "-" * 48)
    total_detections = 0
    sorted_types = sorted(entity_hits.items(), key=lambda x: -len(x[1]))
    for etype, hits in sorted_types:
        avg_score = sum(h["score"] for h in hits) / len(hits)
        print(f"  {etype:<25} {len(hits):>8}  {avg_score:>10.3f}")
        total_detections += len(hits)

    not_fired = [e for e in ALL_ENTITY_TYPES if e not in entity_hits]
    print(f"\n  Total detections: {total_detections}")
    print(f"  Entity types that did NOT fire: {not_fired}")

    # --- 5 examples per entity type ---
    print("\n--- Examples per Entity Type (up to 5) ---")
    for etype, hits in sorted_types:
        print(f"\n  {etype} ({len(hits)} total):")
        for h in hits[:5]:
            print(f"    [{h['ticker']} {h['filing_type']} score={h['score']:.2f}] "
                  f"matched={h['matched']!r}")
            print(f"      context: ...{h['context']}...")

    # --- Policy decisions ---
    print("\n--- Retrieval Rail Policy Decisions ---")
    print("""
  For each entity type, keep vs. redact in the RETRIEVAL rail context:

  PERSON:
    In SEC filings, executive and director names are public information
    (e.g., "Satya Nadella, CEO" in an Executive Officers section). In most
    other sections (proxy disclosures of family members, compensation
    beneficiaries), they are still public record, not personally sensitive.
    Redacting PERSON in retrieved chunks would destroy the narrative of
    corporate governance sections and make answers unreadable.
    DECISION: KEEP (do not redact)
    Exception: personal addresses or contact details for individuals are rare
    in SEC filings and would appear as LOCATION or PHONE_NUMBER, not PERSON.

  LOCATION:
    Filing cover pages contain company headquarters addresses (public).
    Risk factor sections reference geographic markets and facilities (public).
    Personal home addresses of directors or employees (rare) would be redacted,
    but Presidio's LOCATION recognizer fires primarily on cities and countries.
    DECISION: KEEP (company addresses and market geographies are public context)

  PHONE_NUMBER:
    Investor relations phone numbers on cover pages are public. Employee direct
    lines are not expected in 10-K/10-Q body text but could appear in exhibits.
    Presidio's phone recognizer has moderate precision (many false positives on
    financial figures formatted like phone numbers). Redacting adds noise.
    DECISION: KEEP (low actual PII risk; high false positive rate on financial data)
    Note: if empirical data shows personal phone numbers, revisit.

  EMAIL_ADDRESS:
    Investor relations emails are public (e.g., ir@apple.com) but provide no
    downstream value for RAG retrieval quality. Redacting them has no accuracy
    cost. Employee personal emails are rare but possible in certain exhibits.
    DECISION: REDACT (no retrieval value; any false positive is a low-cost miss)

  US_SSN:
    Social security numbers have no place in SEC public filings. If detected,
    it is either a data error or a test of the pipeline.
    DECISION: REDACT (always)

  CREDIT_CARD:
    No legitimate credit card numbers appear in SEC filings.
    DECISION: REDACT (always)

  DATE_TIME:
    SEC filings are heavily date-referenced (fiscal year end, filing date,
    period of report, quarter boundaries). Redacting dates destroys the
    temporal context that makes financial statements meaningful.
    DECISION: KEEP (essential for SEC filing semantics)

  NRP (Nationalities, Religious, Political groups):
    Appears in filings as references to countries/regions/jurisdictions
    (e.g., "U.S. federal tax", "European regulatory"). These are not
    sensitive in context.
    DECISION: KEEP

  IP_ADDRESS:
    Extremely rare in SEC filings. If present, could indicate a data
    infrastructure disclosure that is not PII. Very low detection count.
    DECISION: REDACT (no value; if Presidio fires here it is likely a false
    positive on version numbers or footnote references, but redacting is safe)

  ORGANIZATION:
    SEC filings contain thousands of organization references (subsidiary names,
    counterparties, regulators, exchanges). Redacting would make the text
    unintelligible.
    DECISION: KEEP

  US_DRIVER_LICENSE:
    Not expected in SEC filings. Any detection is a false positive on other
    formatted strings.
    DECISION: REDACT (always, with expect-zero detection count)

  US_BANK_NUMBER:
    Bank account numbers do not appear in SEC narrative text. Could appear in
    financial schedules but Presidio's recognizer has moderate false positive
    rate on financial identifiers.
    DECISION: KEEP (false positive risk exceeds actual PII risk in SEC context)
    Note: the input rail's allowlist redacts US_BANK_NUMBER; for retrieval,
    the same financial-identifier false positive problem applies more strongly
    because SEC filings contain CIK numbers, routing-number-like sequences.

  IBAN_CODE:
    International bank account numbers are extremely rare in SEC 10-K/10-Q
    filings. If detected, likely a false positive on formatted financial data.
    DECISION: KEEP (same reasoning as US_BANK_NUMBER)

  URL:
    SEC filing URLs (EDGAR links, company websites) are public information.
    DECISION: KEEP

  CRYPTO:
    Cryptocurrency wallet addresses are not expected in SEC filings.
    DECISION: REDACT if detected (but expect near-zero hits)

  Retrieval-rail entity types to REDACT:
    EMAIL_ADDRESS, US_SSN, CREDIT_CARD, IP_ADDRESS, US_DRIVER_LICENSE, CRYPTO

  Input-rail entity types (existing PiiRedactionRail — unchanged):
    US_SSN, CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, US_BANK_NUMBER, IBAN_CODE
""")

    print("=" * 72)
    print("END CHARACTERIZATION")
    print("=" * 72)


if __name__ == "__main__":
    random.seed(42)
    run()
