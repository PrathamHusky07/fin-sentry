from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np

from finsentry.frontier.faithjudge.retriever import FinanceBenchPeerRetriever

_THRESHOLD = 0.75
_CEILING = 0.95


def _retriever(**kwargs: object) -> FinanceBenchPeerRetriever:
    mock_model = MagicMock()
    mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
        return FinanceBenchPeerRetriever(
            db_url="unused",
            similarity_threshold=_THRESHOLD,
            leakage_ceiling=_CEILING,
            **kwargs,  # type: ignore[arg-type]
        )


def _candidates(*rows: tuple[str, float]) -> list[tuple[str, str, str, str, float]]:
    """Build (id, question, expected_answer, doc_id, similarity) tuples."""
    return [(id_, f"question {id_}", f"answer {id_}", f"doc-{id_}", sim) for id_, sim in rows]


def _patched_retrieve_sync(return_value: list[tuple[str, str, str, str, float]]) -> MagicMock:
    return MagicMock(return_value=return_value)


def test_top_k_limits_peers_to_configured_k() -> None:
    retriever = _retriever(k=2)
    candidates = _candidates(("a", 0.90), ("b", 0.85), ("c", 0.80), ("d", 0.76))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    assert len(result.peers) == 2
    assert [p.example_id for p in result.peers] == ["a", "b"]
    assert result.k == 2


def test_below_threshold_candidates_are_rejected_with_reason() -> None:
    retriever = _retriever(k=3)
    candidates = _candidates(("a", 0.90), ("b", 0.50))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    assert [p.example_id for p in result.peers] == ["a"]
    assert len(result.rejected) == 1
    assert result.rejected[0].example_id == "b"
    assert result.rejected[0].reason == "below_threshold"


def test_leakage_ceiling_excludes_near_duplicates() -> None:
    retriever = _retriever(k=3)
    candidates = _candidates(("near-dup", 0.98), ("a", 0.90))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    assert [p.example_id for p in result.peers] == ["a"]
    assert len(result.rejected) == 1
    assert result.rejected[0].example_id == "near-dup"
    assert result.rejected[0].reason == "leakage_ceiling"


def test_exact_id_exclusion_is_passed_through_to_the_sql_layer() -> None:
    retriever = _retriever(k=3)
    candidates = _candidates(("other", 0.90))
    mock_sync = _patched_retrieve_sync(candidates)
    with patch("finsentry.frontier.faithjudge.retriever._retrieve_sync", mock_sync):
        asyncio.run(retriever.retrieve("some question", exclude_example_id="self-id"))

    assert mock_sync.call_args[0][2] == "self-id"


def test_zero_peers_is_a_legitimate_result_not_an_error() -> None:
    retriever = _retriever(k=3)
    candidates = _candidates(("a", 0.50), ("b", 0.98))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    assert result.peers == []
    assert len(result.rejected) == 2


def test_provenance_is_preserved_on_peers_and_rejections() -> None:
    retriever = _retriever(k=3)
    candidates = _candidates(("a", 0.90), ("b", 0.50))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    peer = result.peers[0]
    assert peer.example_id == "a"
    assert peer.question == "question a"
    assert peer.expected_answer == "answer a"
    assert peer.doc_id == "doc-a"
    assert peer.dataset == "financebench"
    assert peer.similarity == 0.90
    assert result.k == 3
    assert result.similarity_threshold == _THRESHOLD
    assert result.leakage_ceiling == _CEILING


def test_retrieval_latency_is_recorded() -> None:
    retriever = _retriever(k=3)
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(_candidates(("a", 0.90))),
    ):
        result = asyncio.run(retriever.retrieve("some question"))

    assert result.retrieval_latency_ms >= 0


def test_retrieval_is_deterministic_on_a_fixed_index() -> None:
    retriever = _retriever(k=2)
    candidates = _candidates(("a", 0.90), ("b", 0.85), ("c", 0.50))
    with patch(
        "finsentry.frontier.faithjudge.retriever._retrieve_sync",
        _patched_retrieve_sync(candidates),
    ):
        first = asyncio.run(retriever.retrieve("some question"))
        second = asyncio.run(retriever.retrieve("some question"))

    assert first.peers == second.peers
    assert first.rejected == second.rejected
