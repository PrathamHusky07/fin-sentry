"""Tests for Phase 2: chunk labeling in _build_rag_messages."""
from __future__ import annotations

from finsentry.gateway.main import RetrievedChunk, _build_rag_messages


def _make_chunk(chunk_id: str, text: str = "some text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        ticker="AAPL",
        filing_type="10-K",
        filing_date="2024-09-28",
        source_url="https://www.sec.gov/test",
        text=text,
        similarity_score=0.8,
    )


def test_build_rag_messages_labels_chunks_with_stable_id() -> None:
    chunks = [
        _make_chunk("abc-123", "Revenue was $94.9 billion."),
        _make_chunk("def-456", "Operating income was $29.6 billion."),
    ]
    messages = _build_rag_messages("What was Apple revenue?", chunks)
    user_msg = messages[1]["content"]
    assert "[chunk_id=abc-123]" in user_msg
    assert "[chunk_id=def-456]" in user_msg


def test_build_rag_messages_instructs_empty_citations_on_no_info() -> None:
    chunks = [_make_chunk("xyz-789")]
    messages = _build_rag_messages("What was Apple revenue?", chunks)
    system_msg = messages[0]["content"]
    # Must instruct model to return empty citations list when context is insufficient
    assert "citations" in system_msg.lower() and "[]" in system_msg
    # Must instruct model to set confidence "low" in the abstention case
    assert 'confidence' in system_msg and '"low"' in system_msg
