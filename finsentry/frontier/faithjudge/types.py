"""
FaithJudge peer-example retrieval domain contract.

Dataset-agnostic by design: PeerExample and PeerRetriever carry no
FinanceBench-specific fields, so a FinQA retriever can plug in later behind
the same protocol (see finsentry/frontier/faithjudge/retriever.py for the
FinanceBench implementation — the only one M2 builds).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass
class PeerExample:
    """One human-annotated golden-set example surfaced as a few-shot peer.

    Fields mirror golden_set's own columns exactly (example_id = the
    dataset's native id, e.g. financebench_id) plus the two fields the
    retrieval act itself produces: dataset and similarity.
    """

    example_id: str
    question: str
    expected_answer: str
    doc_id: str
    dataset: str
    similarity: float


RejectionReason = Literal["below_threshold", "leakage_ceiling"]


@dataclass
class RejectedPeer:
    """A candidate considered but not surfaced, with the reason why."""

    example_id: str
    similarity: float
    reason: RejectionReason


@dataclass
class PeerRetrievalResult:
    """Full observability record for one retrieval call.

    peers is the usable few-shot set (already filtered and capped at k).
    rejected covers only candidates that were in the similarity window
    actually inspected — it is not a dump of the whole dataset. k,
    similarity_threshold, and leakage_ceiling record the config in effect
    at call time so a trace is self-describing even if defaults change
    later.
    """

    peers: list[PeerExample]
    rejected: list[RejectedPeer]
    k: int
    similarity_threshold: float
    leakage_ceiling: float
    retrieval_latency_ms: int


@runtime_checkable
class PeerRetriever(Protocol):
    """A dataset-specific peer-example retriever.

    dataset identifies which golden corpus this retriever draws from (e.g.
    "financebench"). retrieve() takes the current question and an optional
    exact-id to exclude (set when the item under evaluation is itself a
    golden-set row, e.g. during Day 6 calibration) and returns every peer
    actually used plus full rejection provenance.
    """

    dataset: str

    async def retrieve(
        self, question: str, exclude_example_id: str | None = None
    ) -> PeerRetrievalResult: ...
