from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import edgar
import psycopg
import tiktoken
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# Module-level singletons. Model download (~130 MB) happens once and is cached
# in ~/.cache/huggingface/ on subsequent imports.
_MODEL: SentenceTransformer = SentenceTransformer("BAAI/bge-small-en-v1.5")
_ENC = tiktoken.get_encoding("cl100k_base")
_SPLITTER = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base",
    chunk_size=800,
    chunk_overlap=100,
)

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "JPM", "BRK-B", "TSLA", "WMT"]
FILING_SPEC: dict[str, int] = {"10-K": 2, "10-Q": 4, "8-K": 20}
_BATCH_SIZE = 500

_INSERT = """
INSERT INTO corpus (
    id, ticker, filing_type, accession_number, filing_date, period_of_report,
    chunk_index, chunk_text, chunk_tokens, embedding, source_url
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""


def _chunk_id(ticker: str, accession_number: str, chunk_index: int) -> str:
    return hashlib.sha256(
        f"{ticker}\x00{accession_number}\x00{chunk_index}".encode()
    ).hexdigest()[:16]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def _download_text(filing: Any) -> str:
    """Download filing text, preferring markdown (strips boilerplate) over raw text."""
    try:
        text: str = filing.document.markdown()
        return text
    except Exception:
        log.debug("markdown() failed, falling back to text() for %s", filing.accession_number)
        result: str = filing.document.text()
        return result


def _flush(cur: psycopg.Cursor[Any], rows: list[tuple[Any, ...]]) -> None:
    for i in range(0, len(rows), _BATCH_SIZE):
        cur.executemany(_INSERT, rows[i : i + _BATCH_SIZE])


def _ingest_ticker(
    cur: psycopg.Cursor[Any],
    ticker: str,
    filing_spec: dict[str, int],
) -> None:
    company = edgar.Company(ticker)
    for form_type, limit in filing_spec.items():
        filings = company.get_filings(form=form_type)
        subset = list(filings[:limit])
        if len(subset) < limit:
            log.warning(
                "%s %s: only %d filings available (requested %d)",
                ticker, form_type, len(subset), limit,
            )

        rows: list[tuple[Any, ...]] = []
        for filing in subset:
            accession_number: str = filing.accession_number
            filing_date = filing.filing_date
            period_of_report = filing.period_of_report
            source_url: str = filing.filing_url

            try:
                text = _download_text(filing)
            except Exception as exc:
                log.warning(
                    "Skipping %s %s %s after retries: %s",
                    ticker, form_type, accession_number, exc,
                )
                continue

            chunks = _SPLITTER.split_text(text)
            if not chunks:
                log.warning("No chunks produced for %s %s %s", ticker, form_type, accession_number)
                continue

            # SentenceTransformer.encode returns np.ndarray; annotated as Any
            # because numpy stubs use 3.12 syntax incompatible with our 3.11 target.
            embeddings: Any = _MODEL.encode(chunks, batch_size=32, show_progress_bar=False)
            for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
                rows.append((
                    _chunk_id(ticker, accession_number, idx),
                    ticker,
                    form_type,
                    accession_number,
                    filing_date,
                    period_of_report,
                    idx,
                    chunk_text,
                    len(_ENC.encode(chunk_text)),
                    embedding,
                    source_url,
                ))

        _flush(cur, rows)
        log.info("%s  %s  %d chunks inserted", ticker, form_type, len(rows))


def ingest(
    database_url: str,
    tickers: list[str] | None = None,
    filing_spec: dict[str, int] | None = None,
) -> None:
    identity = os.getenv("EDGAR_IDENTITY", "")
    if not identity:
        raise RuntimeError(
            "EDGAR_IDENTITY is not set. "
            "Add it to .env: EDGAR_IDENTITY=<AppName> <email@example.com>"
        )
    edgar.set_identity(identity)

    effective_tickers = tickers if tickers is not None else TICKERS
    effective_spec = filing_spec if filing_spec is not None else FILING_SPEC

    with psycopg.connect(database_url, autocommit=True) as conn:
        # register_vector teaches psycopg3 how to serialise numpy arrays into
        # the Postgres vector type. Must be called once per connection.
        register_vector(conn)
        with conn.cursor() as cur:
            for ticker in effective_tickers:
                _ingest_ticker(cur, ticker, effective_spec)


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    ingest(os.environ["DATABASE_URL"])
