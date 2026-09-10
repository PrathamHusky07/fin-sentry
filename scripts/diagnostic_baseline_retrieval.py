"""
Baseline retrieval diagnostic — 20 categorized queries.

Tests the retrieval pipeline (embed -> vector search -> retrieval rail) directly
without calling the downstream LLM. This characterizes retrieval quality, cross-
ticker pollution, temporal retrieval, and the retrieval rail filtering behavior
as a baseline before Session C evaluation work.

Failure modes detected:
  CROSS_TICKER_POLLUTION   -- chunks for wrong company in top-k (ticker filter set)
  EXPECTED_TICKER_MISSING  -- cross-company query missing an expected ticker
  LOW_SIM_CEILING          -- all top-k similarity scores below 0.5
  HIGH_SCORE_VARIANCE      -- top-1 score more than 0.3 above last chunk (unstable)
  MULTI_COMPANY_RETURN     -- ticker filter set but multiple companies returned
  RAIL_DROPPED_ALL         -- retrieval rail removed every chunk
  RAIL_DROPPED_SOME        -- retrieval rail removed at least one chunk
  PII_REDACTED             -- at least one chunk had text mutated by Presidio

Usage:
  PYTHONPATH=. python scripts/diagnostic_baseline_retrieval.py

Requires the Docker Compose stack (postgres + pgvector). Does NOT require the
gateway server or Ollama to be running.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
TOP_K = 5

# ---------------------------------------------------------------------------
# Query catalog: 20 queries across 5 categories
# ---------------------------------------------------------------------------

QUERIES: list[dict[str, Any]] = [
    # Category 1: Single-company financial metrics (5 queries)
    {
        "id": "M01",
        "category": "single-company-metric",
        "query": "What was Apple total revenue for fiscal year 2024?",
        "ticker": "AAPL",
        "expected_tickers": {"AAPL"},
    },
    {
        "id": "M02",
        "category": "single-company-metric",
        "query": "What is Microsoft cloud revenue for the most recent quarter?",
        "ticker": "MSFT",
        "expected_tickers": {"MSFT"},
    },
    {
        "id": "M03",
        "category": "single-company-metric",
        "query": "What is NVIDIA gross margin percentage?",
        "ticker": "NVDA",
        "expected_tickers": {"NVDA"},
    },
    {
        "id": "M04",
        "category": "single-company-metric",
        "query": "What is Amazon operating income for AWS?",
        "ticker": "AMZN",
        "expected_tickers": {"AMZN"},
    },
    {
        "id": "M05",
        "category": "single-company-metric",
        "query": "What is JPMorgan Chase net interest income?",
        "ticker": "JPM",
        "expected_tickers": {"JPM"},
    },
    # Category 2: Risk factors and disclosures (4 queries)
    {
        "id": "R01",
        "category": "risk-disclosure",
        "query": "What are Meta key risk factors related to regulatory compliance?",
        "ticker": "META",
        "expected_tickers": {"META"},
    },
    {
        "id": "R02",
        "category": "risk-disclosure",
        "query": "What geopolitical risks does Tesla disclose in its 10-K?",
        "ticker": "TSLA",
        "expected_tickers": {"TSLA"},
    },
    {
        "id": "R03",
        "category": "risk-disclosure",
        "query": "What supply chain risks does Walmart face according to SEC filings?",
        "ticker": "WMT",
        "expected_tickers": {"WMT"},
    },
    {
        "id": "R04",
        "category": "risk-disclosure",
        "query": "What are the key risks for Berkshire Hathaway insurance operations?",
        "ticker": "BRK-B",
        "expected_tickers": {"BRK-B"},
    },
    # Category 3: Cross-company comparison (no ticker filter) (3 queries)
    {
        "id": "C01",
        "category": "cross-company",
        "query": "Compare revenue growth rates for Apple and Microsoft.",
        "ticker": None,
        "expected_tickers": {"AAPL", "MSFT"},
    },
    {
        "id": "C02",
        "category": "cross-company",
        "query": "Which technology companies disclose AI-related risks in their filings?",
        "ticker": None,
        "expected_tickers": {"AAPL", "MSFT", "NVDA", "GOOGL", "META"},
    },
    {
        "id": "C03",
        "category": "cross-company",
        "query": "What are capital allocation priorities for large financial institutions?",
        "ticker": None,
        "expected_tickers": {"JPM", "BRK-B"},
    },
    # Category 4: Temporal specificity (4 queries)
    {
        "id": "T01",
        "category": "temporal",
        "query": "What was Google advertising revenue in the most recent annual period?",
        "ticker": "GOOGL",
        "expected_tickers": {"GOOGL"},
    },
    {
        "id": "T02",
        "category": "temporal",
        "query": "What did NVIDIA report for Q2 fiscal year 2025 data center revenue?",
        "ticker": "NVDA",
        "expected_tickers": {"NVDA"},
    },
    {
        "id": "T03",
        "category": "temporal",
        "query": "What was Apple iPhone revenue in Q4 2023?",
        "ticker": "AAPL",
        "expected_tickers": {"AAPL"},
    },
    {
        "id": "T04",
        "category": "temporal",
        "query": "What guidance did Microsoft give for fiscal year 2025?",
        "ticker": "MSFT",
        "expected_tickers": {"MSFT"},
    },
    # Category 5: Stress / adversarial queries (4 queries)
    {
        "id": "S01",
        "category": "stress",
        "query": "Tell me everything about every company in the S&P 500 index.",
        "ticker": None,
        "expected_tickers": set(),
    },
    {
        "id": "S02",
        "category": "stress",
        "query": "What is the salary of the CEO?",
        "ticker": "AAPL",
        "expected_tickers": {"AAPL"},
    },
    {
        "id": "S03",
        "category": "stress",
        "query": "abcdefghij xyzxyzxyz nonsense query with no semantic match.",
        "ticker": None,
        "expected_tickers": set(),
    },
    {
        "id": "S04",
        "category": "stress",
        "query": "What is the exact price of Apple stock today?",
        "ticker": "AAPL",
        "expected_tickers": set(),
    },
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ChunkResult:
    chunk_id: str
    ticker: str
    filing_type: str
    filing_date: str
    similarity_score: float
    text_before: str
    text_after: str


@dataclass
class QueryResult:
    query_id: str
    category: str
    query: str
    ticker: str | None
    expected_tickers: set[str]
    embed_ms: float
    search_ms: float
    rail_ms: float
    raw_chunk_count: int
    filtered_chunk_count: int
    chunks: list[ChunkResult] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_raw(
    db_url: str,
    embedding: list[float],
    ticker: str | None,
    top_k: int,
) -> list[ChunkResult]:
    import numpy as np
    import psycopg
    from pgvector.psycopg import register_vector

    vec = np.array(embedding, dtype=np.float32)

    if ticker is not None:
        sql = """
            SELECT id, ticker, filing_type, filing_date::text, chunk_text,
                   1 - (embedding <=> %s::vector) AS sim
            FROM corpus WHERE ticker = %s
            ORDER BY embedding <=> %s::vector LIMIT %s
        """
        params: tuple[Any, ...] = (vec, ticker, vec, top_k)
    else:
        sql = """
            SELECT id, ticker, filing_type, filing_date::text, chunk_text,
                   1 - (embedding <=> %s::vector) AS sim
            FROM corpus
            ORDER BY embedding <=> %s::vector LIMIT %s
        """
        params = (vec, vec, top_k)

    with psycopg.connect(db_url, autocommit=True) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        ChunkResult(
            chunk_id=str(r[0]),
            ticker=str(r[1]),
            filing_type=str(r[2]),
            filing_date=str(r[3]) if r[3] else "",
            similarity_score=float(r[5]),
            text_before=str(r[4]),
            text_after=str(r[4]),
        )
        for r in rows
    ]


def _detect_failure_modes(result: QueryResult) -> list[str]:
    modes: list[str] = []

    if result.error:
        modes.append(f"ERROR:{result.error[:50]}")
        return modes

    if result.raw_chunk_count == 0:
        modes.append("NO_CHUNKS_RETURNED")
        return modes

    if result.filtered_chunk_count == 0 and result.raw_chunk_count > 0:
        modes.append("RAIL_DROPPED_ALL")
        return modes

    scores = [c.similarity_score for c in result.chunks]
    max_score = max(scores) if scores else 0.0

    # Failure A: Cross-ticker pollution
    if result.ticker is not None:
        wrong = {c.ticker for c in result.chunks} - {result.ticker}
        if wrong:
            modes.append(f"CROSS_TICKER_POLLUTION:{','.join(sorted(wrong))}")

    # Failure B: Expected tickers missing
    if result.expected_tickers:
        returned = {c.ticker for c in result.chunks}
        missing = result.expected_tickers - returned
        if missing:
            modes.append(f"EXPECTED_TICKER_MISSING:{','.join(sorted(missing))}")

    # Failure C: Low similarity ceiling
    if max_score < 0.5:
        modes.append(f"LOW_SIM_CEILING:max={max_score:.3f}")

    # Failure D: High score variance (top-1 much better than tail)
    if len(scores) >= 2 and (scores[0] - scores[-1]) > 0.3:
        modes.append(f"HIGH_SCORE_VARIANCE:spread={scores[0]-scores[-1]:.3f}")

    # Failure E: Multi-company return when single ticker expected
    if result.ticker is not None:
        unique = {c.ticker for c in result.chunks}
        if len(unique) > 1:
            modes.append(f"MULTI_COMPANY_RETURN:{len(unique)}_tickers")

    # Info: rail dropped some chunks
    if result.filtered_chunk_count < result.raw_chunk_count:
        dropped = result.raw_chunk_count - result.filtered_chunk_count
        modes.append(f"RAIL_DROPPED_SOME:{dropped}_of_{result.raw_chunk_count}")

    # Info: text mutation detected (PII redaction by Presidio)
    redacted = [
        c for c in result.chunks if c.text_after != c.text_before
    ]
    if redacted:
        modes.append(f"PII_REDACTED:{len(redacted)}_chunks")

    return modes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_diagnostic() -> None:
    print("=" * 72)
    print("Baseline Retrieval Diagnostic — 20 queries, 5 categories")
    print("=" * 72)
    print()
    print("Loading embedding model (BAAI/bge-small-en-v1.5)...")
    embed_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    print("Model loaded.\n")

    from finsentry.rails.retrieval.rail import RetrievalRail
    from finsentry.gateway.main import RetrievedChunk

    rail = RetrievalRail(db_url=DATABASE_URL)

    results: list[QueryResult] = []

    for q in QUERIES:
        error = ""
        try:
            t0 = time.monotonic()
            embedding: list[float] = embed_model.encode(
                [q["query"]], show_progress_bar=False
            )[0].tolist()
            embed_ms = (time.monotonic() - t0) * 1000.0

            t1 = time.monotonic()
            raw_chunks = _fetch_raw(DATABASE_URL, embedding, q["ticker"], TOP_K)
            search_ms = (time.monotonic() - t1) * 1000.0

            # Convert to RetrievedChunk objects for the rail
            rc_list = [
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    ticker=c.ticker,
                    filing_type=c.filing_type,
                    filing_date=c.filing_date,
                    text=c.text_before,
                    similarity_score=c.similarity_score,
                )
                for c in raw_chunks
            ]

            t2 = time.monotonic()
            filtered = rail.check_chunks(rc_list)
            rail_ms = (time.monotonic() - t2) * 1000.0

            # Rebuild ChunkResult from filtered, carrying redacted text
            chunk_results: list[ChunkResult] = []
            filtered_ids = {fc.chunk_id: fc for fc in filtered}
            for rc in rc_list:
                if rc.chunk_id in filtered_ids:
                    fc = filtered_ids[rc.chunk_id]
                    chunk_results.append(
                        ChunkResult(
                            chunk_id=rc.chunk_id,
                            ticker=rc.ticker,
                            filing_type=rc.filing_type,
                            filing_date=rc.filing_date,
                            similarity_score=rc.similarity_score,
                            text_before=rc.text,
                            text_after=fc.text,
                        )
                    )

        except Exception as exc:
            embed_ms = search_ms = rail_ms = 0.0
            raw_chunks = []
            filtered = []
            chunk_results = []
            error = str(exc)[:120]

        result = QueryResult(
            query_id=str(q["id"]),
            category=str(q["category"]),
            query=str(q["query"]),
            ticker=q["ticker"],
            expected_tickers=set(q["expected_tickers"]),
            embed_ms=embed_ms,
            search_ms=search_ms,
            rail_ms=rail_ms,
            raw_chunk_count=len(raw_chunks),
            filtered_chunk_count=len(filtered),
            chunks=chunk_results,
            error=error,
        )
        result.failure_modes = _detect_failure_modes(result)
        results.append(result)

        total_ms = embed_ms + search_ms + rail_ms
        status = "OK" if not result.failure_modes else f"ISSUE({len(result.failure_modes)})"
        print(
            f"[{result.query_id}] {result.category:<22}  {status:<16}"
            f"  raw={result.raw_chunk_count}  filtered={result.filtered_chunk_count}"
            f"  {total_ms:.0f}ms"
        )
        if result.failure_modes:
            for mode in result.failure_modes:
                print(f"         -> {mode}")
        if result.error:
            print(f"         ERROR: {result.error}")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------

    print()
    print("=" * 72)
    print("SUMMARY REPORT")
    print("=" * 72)

    total = len(results)
    clean = sum(1 for r in results if not r.failure_modes)
    print(f"\nTotal queries       : {total}")
    print(f"Clean (no failures) : {clean}/{total}")
    print(f"With failure modes  : {total - clean}/{total}")
    print()

    mode_counts: dict[str, int] = {}
    for r in results:
        for mode in r.failure_modes:
            key = mode.split(":")[0]
            mode_counts[key] = mode_counts.get(key, 0) + 1

    if mode_counts:
        print("Failure mode frequency:")
        for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
            print(f"  {mode:<35}  {count:>3} / {total}")
    else:
        print("No failure modes detected.")

    print()
    categories = sorted({r.category for r in results})
    print("Per-category breakdown:")
    for cat in categories:
        cat_r = [r for r in results if r.category == cat]
        cat_clean = sum(1 for r in cat_r if not r.failure_modes)
        avg_search = sum(r.search_ms for r in cat_r) / len(cat_r)
        scored = [r for r in cat_r if r.chunks]
        avg_top1 = (
            sum(r.chunks[0].similarity_score for r in scored) / len(scored)
            if scored else 0.0
        )
        print(
            f"  {cat:<25}  clean={cat_clean}/{len(cat_r)}"
            f"  avg_search={avg_search:.0f}ms"
            f"  avg_top1_sim={avg_top1:.3f}"
        )

    print()
    # Top-1 sim stats
    top1 = sorted(r.chunks[0].similarity_score for r in results if r.chunks)
    if top1:
        p50 = top1[len(top1) // 2]
        print(f"Top-1 similarity: min={min(top1):.3f}  p50={p50:.3f}  max={max(top1):.3f}")

    # Per-query detailed
    print()
    print("=" * 72)
    print("DETAILED RESULTS")
    print("=" * 72)
    for r in results:
        print(f"\n[{r.query_id}] {r.query}")
        print(
            f"  cat={r.category}  ticker={r.ticker}  "
            f"raw={r.raw_chunk_count}  filtered={r.filtered_chunk_count}  "
            f"embed={r.embed_ms:.0f}ms  search={r.search_ms:.0f}ms  rail={r.rail_ms:.0f}ms"
        )
        if r.failure_modes:
            print(f"  failure_modes: {r.failure_modes}")
        for c in r.chunks:
            label = "[PII_REDACTED]" if c.text_after != c.text_before else ""
            print(
                f"    {c.ticker}/{c.filing_type}/{c.filing_date}"
                f"  sim={c.similarity_score:.3f}"
                f"  id={c.chunk_id}"
                f"  {label}"
            )
            print(f"    {c.text_after[:120].replace(chr(10),' ')!r}")
        if r.error:
            print(f"  ERROR: {r.error}")

    # JSON summary for build log
    print()
    summary = {
        "total": total,
        "clean": clean,
        "failure_mode_counts": mode_counts,
        "results": [
            {
                "id": r.query_id,
                "category": r.category,
                "ticker": r.ticker,
                "raw_chunks": r.raw_chunk_count,
                "filtered_chunks": r.filtered_chunk_count,
                "search_ms": round(r.search_ms, 1),
                "rail_ms": round(r.rail_ms, 1),
                "top1_sim": round(r.chunks[0].similarity_score, 4) if r.chunks else None,
                "failure_modes": r.failure_modes,
            }
            for r in results
        ],
    }
    print("JSON summary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_diagnostic()
