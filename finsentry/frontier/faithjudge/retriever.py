"""
FinanceBench peer-example retriever.

Embeds the current question with its own SentenceTransformer instance,
constructed once at __init__ (not per-call, and not imported from
finsentry.gateway.main._embed_model — that global lives in the gateway's own
process; this retriever runs inside the frontier consumer process). Cosine
search over golden_set mirrors the gateway's pgvector pattern exactly: `1 -
(embedding <=> %s::vector)`.

Contamination control is two-layered, deliberately not relying on exact-id
matching alone:
  1. exclude_example_id: an explicit exact-id exclusion for when the item
     under evaluation IS itself a golden-set row (Day 6 calibration does
     this constantly).
  2. leakage_ceiling: ANY candidate whose similarity to the current question
     exceeds this ceiling is excluded, regardless of id. A paraphrased
     near-duplicate has no matching id but can still leak the ground-truth
     answer into the prompt, so similarity-ceiling exclusion is the layer
     that actually controls for that — exact-id exclusion alone is
     insufficient and must never be treated as the only guard. This is a
     control, not a proof that all semantic leakage is impossible: a
     sufficiently different phrasing of the same underlying fact could still
     slip under the ceiling.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from finsentry.frontier.faithjudge.types import PeerExample, PeerRetrievalResult, RejectedPeer

log = logging.getLogger(__name__)

_DEFAULT_K = 3

# Provisional configuration defaults, not calibrated (Day 6 calibration is
# explicitly out of scope for M2). An exploratory check of the embedded
# golden set's own pairwise cosine similarities (150 FinanceBench questions,
# bge-small-en-v1.5) showed: median 0.57, 95th percentile 0.72, max 0.969.
# similarity_threshold=0.75 keeps peers genuinely topically close rather
# than "any other finance question"; leakage_ceiling=0.95 sits just under
# the observed max so only true near-duplicates are excluded as a
# contamination risk.
_DEFAULT_SIMILARITY_THRESHOLD = 0.75
_DEFAULT_LEAKAGE_CEILING = 0.95

# Candidates pulled from the DB before filtering — wide enough to leave
# headroom past k after leakage/threshold rejection; bounded since
# golden_set is only 150 rows.
_DEFAULT_CANDIDATE_POOL_SIZE = 20


def _retrieve_sync(
    db_url: str,
    query_embedding: list[float],
    exclude_example_id: str | None,
    pool_size: int,
) -> list[tuple[str, str, str, str, float]]:
    """Sync psycopg call wrapped in asyncio.to_thread by retrieve().

    Returns (example_id, question, expected_answer, doc_id, similarity)
    tuples ordered by descending similarity; ties broken by id so repeated
    calls against an unchanged index are deterministic.
    """
    vec = np.array(query_embedding, dtype=np.float32)

    if exclude_example_id is not None:
        sql = """
            SELECT id, question, expected_answer, doc_id,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM golden_set
            WHERE embedding IS NOT NULL AND id != %s
            ORDER BY embedding <=> %s::vector, id
            LIMIT %s
        """
        params: tuple[Any, ...] = (vec, exclude_example_id, vec, pool_size)
    else:
        sql = """
            SELECT id, question, expected_answer, doc_id,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM golden_set
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector, id
            LIMIT %s
        """
        params = (vec, vec, pool_size)

    with psycopg.connect(db_url, autocommit=True) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows: list[Any] = cur.fetchall()

    return [(str(r[0]), str(r[1]), str(r[2]), str(r[3]), float(r[4])) for r in rows]


class FinanceBenchPeerRetriever:
    """PeerRetriever over golden_set's FinanceBench rows."""

    dataset = "financebench"

    def __init__(
        self,
        db_url: str,
        k: int = _DEFAULT_K,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        leakage_ceiling: float = _DEFAULT_LEAKAGE_CEILING,
        candidate_pool_size: int = _DEFAULT_CANDIDATE_POOL_SIZE,
    ) -> None:
        self._db_url = db_url
        self._k = k
        self._similarity_threshold = similarity_threshold
        self._leakage_ceiling = leakage_ceiling
        self._candidate_pool_size = candidate_pool_size

        from sentence_transformers import SentenceTransformer

        self._embed_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        # One encode at a time. The model may sit on the MPS device, and concurrent
        # encodes from several handler threads segfault the process.
        self._encode_lock = asyncio.Lock()

    async def retrieve(
        self, question: str, exclude_example_id: str | None = None
    ) -> PeerRetrievalResult:
        start = time.monotonic()

        async with self._encode_lock:
            embedding: list[float] = (
                await asyncio.to_thread(
                    lambda: self._embed_model.encode([question], show_progress_bar=False)
                )
            )[0].tolist()

        candidates = await asyncio.to_thread(
            _retrieve_sync,
            self._db_url,
            embedding,
            exclude_example_id,
            self._candidate_pool_size,
        )

        peers: list[PeerExample] = []
        rejected: list[RejectedPeer] = []
        for example_id, cand_question, expected_answer, doc_id, similarity in candidates:
            if similarity > self._leakage_ceiling:
                rejected.append(RejectedPeer(example_id, similarity, "leakage_ceiling"))
                continue
            if similarity < self._similarity_threshold:
                rejected.append(RejectedPeer(example_id, similarity, "below_threshold"))
                continue
            if len(peers) >= self._k:
                continue
            peers.append(
                PeerExample(
                    example_id=example_id,
                    question=cand_question,
                    expected_answer=expected_answer,
                    doc_id=doc_id,
                    dataset=self.dataset,
                    similarity=similarity,
                )
            )

        retrieval_latency_ms = int((time.monotonic() - start) * 1000)
        return PeerRetrievalResult(
            peers=peers,
            rejected=rejected,
            k=self._k,
            similarity_threshold=self._similarity_threshold,
            leakage_ceiling=self._leakage_ceiling,
            retrieval_latency_ms=retrieval_latency_ms,
        )
