"""
Backfill embeddings for golden_set.question using BAAI/bge-small-en-v1.5.

Standalone script: instantiates its own SentenceTransformer rather than
importing finsentry.gateway.main._embed_model, which lives in the gateway's
own process. Idempotent — only rows with embedding IS NULL are updated, so
re-running after a partial failure or a later golden-set append is safe.

Run with:
    python scripts/embed_golden_set.py
"""
from __future__ import annotations

import os

import numpy as np
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector


def backfill(database_url: str) -> tuple[int, int]:
    """Embed every golden_set row with embedding IS NULL.

    Returns (embedded_count, total_count).
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-small-en-v1.5")

    with psycopg.connect(database_url, autocommit=True) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM golden_set")
            total_count = cur.fetchone()[0]

            cur.execute("SELECT id, question FROM golden_set WHERE embedding IS NULL")
            rows: list[tuple[str, str]] = cur.fetchall()

            embedded_count = 0
            for row_id, question in rows:
                vec = model.encode([question], show_progress_bar=False)[0]
                cur.execute(
                    "UPDATE golden_set SET embedding = %s WHERE id = %s",
                    (np.asarray(vec, dtype=np.float32), row_id),
                )
                embedded_count += 1

    return embedded_count, total_count


if __name__ == "__main__":
    load_dotenv()
    embedded, total = backfill(os.environ["DATABASE_URL"])
    print(f"Embedded {embedded} previously-unembedded rows out of {total} total golden_set rows.")
