"""Tests for Prompt Guard 2 long-input chunking (p3c-4).

Tests cover the _chunk_input function and the updated check() method that
max-pools malicious probability across all chunks. All tests mock the tokenizer
and classifier so no model download is required.

Key invariant: a malicious instruction placed beyond token 512 (which was
silently dropped by the prior truncation=True, max_length=512 implementation)
is now detected. test_malicious_in_last_chunk_blocks is the regression guard
for the long-input truncation bypass.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import finsentry.rails.input.prompt_guard as pg_module
from finsentry.rails.input.prompt_guard import (
    PromptGuard2Rail,
    _chunk_input,
)

# ---------------------------------------------------------------------------
# Tokenizer mock helpers
# ---------------------------------------------------------------------------


def _make_tokenizer_mock(n_tokens: int) -> MagicMock:
    """Return a tokenizer mock that produces exactly n_tokens IDs for any input.

    Decode returns a deterministic string so chunk text is predictable.
    """
    mock_tok = MagicMock()
    mock_tok.return_value = {"input_ids": list(range(n_tokens))}

    def _decode(ids: list[int], **_: Any) -> str:
        if not ids:
            return ""
        return f"chunk_{ids[0]}_{ids[-1]}"

    mock_tok.decode = MagicMock(side_effect=_decode)
    return mock_tok


def _make_pipeline_mock(
    chunk_probs: list[float],
    n_input_tokens: int,
) -> MagicMock:
    """Return a pipeline mock that produces given per-chunk probabilities.

    The pipeline is called with a list of chunk texts and returns a list of
    per-chunk score lists (batch API format). chunk_probs[i] is the malicious
    probability for chunk i. The mock tokenizer produces n_input_tokens IDs.
    """
    mock_tok = _make_tokenizer_mock(n_input_tokens)

    def _pipe_call(inputs: Any, **_: Any) -> list[list[dict[str, Any]]]:
        texts: list[str] = inputs if isinstance(inputs, list) else [inputs]
        results: list[list[dict[str, Any]]] = []
        for i, _ in enumerate(texts):
            prob = chunk_probs[i] if i < len(chunk_probs) else 0.0
            results.append([
                {"label": "LABEL_1", "score": prob},
                {"label": "LABEL_0", "score": 1.0 - prob},
            ])
        return results

    mock_pipe = MagicMock(side_effect=_pipe_call)
    mock_pipe.tokenizer = mock_tok
    return mock_pipe


# ---------------------------------------------------------------------------
# _chunk_input unit tests
# ---------------------------------------------------------------------------


def test_short_input_single_chunk() -> None:
    """100-token input fits in one window — _chunk_input returns [content] unchanged."""
    tok = _make_tokenizer_mock(100)
    original = "short financial query"
    result = _chunk_input(original, tok)
    assert result == [original]
    # No decode calls: short-circuit returns [content] without tokenize/decode round-trip.
    tok.decode.assert_not_called()


def test_input_at_exact_token_limit() -> None:
    """Exactly 512 tokens is still a single chunk (boundary is inclusive)."""
    tok = _make_tokenizer_mock(512)
    original = "exactly 512 tokens"
    result = _chunk_input(original, tok)
    assert result == [original]
    tok.decode.assert_not_called()


def test_input_just_over_limit() -> None:
    """513 tokens produces two chunks with no token dropped.

    Chunk 0: tokens [0..511] (512 tokens).
    Chunk 1: token [512] (1 token).
    Every token appears in exactly one chunk.
    """
    tok = _make_tokenizer_mock(513)
    result = _chunk_input("513 token input", tok)
    assert len(result) == 2

    # Verify decode was called for each chunk with the right token ranges.
    calls = tok.decode.call_args_list
    assert len(calls) == 2
    first_chunk_ids: list[int] = calls[0][0][0]
    second_chunk_ids: list[int] = calls[1][0][0]
    assert len(first_chunk_ids) == 512
    assert first_chunk_ids[0] == 0
    assert first_chunk_ids[-1] == 511
    assert len(second_chunk_ids) == 1
    assert second_chunk_ids[0] == 512  # no token dropped


def test_chunk_stride_non_overlapping() -> None:
    """1024 tokens with default overlap=0 produces exactly 2 equal chunks."""
    tok = _make_tokenizer_mock(1024)
    result = _chunk_input("1024 token input", tok)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# check() unit tests — classifier behavior per chunk
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_module_restored() -> Any:
    saved = pg_module._pipeline
    yield
    pg_module._pipeline = saved


async def test_long_benign_input_passes(pg_module_restored: Any) -> None:
    """All chunks return low malicious probability — rail passes."""
    # 1200 tokens → 3 chunks; all below threshold.
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.01, 0.02, 0.03],
        n_input_tokens=1200,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("long benign SEC filing text", {})
    assert decision.outcome == "pass"
    assert decision.details["chunk_count"] == 3
    assert decision.details["max_chunk_probability"] < 0.5


async def test_malicious_in_first_chunk_blocks(pg_module_restored: Any) -> None:
    """High malicious probability in chunk 0, low in chunk 1 — rail blocks."""
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.97, 0.02],
        n_input_tokens=1024,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("injection in first chunk", {})
    assert decision.outcome == "block"
    assert decision.details["max_chunk_probability"] >= 0.9


async def test_malicious_in_last_chunk_blocks(pg_module_restored: Any) -> None:
    """High malicious probability in chunk 1 (tail), low in chunk 0 — rail blocks.

    This is the regression guard for the long-input truncation bypass. With the
    prior truncation=True, max_length=512 implementation, a malicious instruction
    placed beyond token 512 was silently dropped and this test would fail
    (outcome "pass" instead of "block").
    """
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.01, 0.99],
        n_input_tokens=1024,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("benign prefix then injection in second chunk", {})
    assert decision.outcome == "block"
    assert decision.details["max_chunk_probability"] >= 0.9


async def test_max_pool_uses_highest_probability(pg_module_restored: Any) -> None:
    """Three chunks with probs [0.1, 0.6, 0.2] — max_chunk_probability is 0.6."""
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.1, 0.6, 0.2],
        n_input_tokens=1536,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("multi-chunk input", {})
    assert decision.outcome == "block"  # 0.6 >= 0.5
    assert abs(decision.details["max_chunk_probability"] - 0.6) < 1e-6


async def test_short_input_behaves_identically_to_prior_implementation(
    pg_module_restored: Any,
) -> None:
    """Short input (100 tokens) → single chunk → single classifier call.

    Verifies the short-input invariant: behavior is byte-for-byte identical
    to the prior single-call implementation for inputs under 512 tokens.
    """
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.97],
        n_input_tokens=100,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("short malicious prompt", {})
    assert decision.outcome == "block"
    assert decision.details["chunk_count"] == 1
    assert decision.details["max_chunk_probability"] >= 0.9


async def test_chunk_count_in_details(pg_module_restored: Any) -> None:
    """chunk_count in details reflects the actual number of chunks processed."""
    # 1536 tokens → 3 chunks of 512 each.
    pg_module._pipeline = _make_pipeline_mock(
        chunk_probs=[0.01, 0.02, 0.03],
        n_input_tokens=1536,
    )
    rail = PromptGuard2Rail()
    decision = rail.check("long benign input", {})
    assert decision.details["chunk_count"] == 3


async def test_classifier_exception_propagates(pg_module_restored: Any) -> None:
    """Pipeline exception propagates; adapter converts to fail-closed BLOCKED via rail contract.

    This mirrors the existing test_prompt_guard_pipeline_crash_propagates in
    test_rails.py. It is repeated here to confirm the exception path is
    unchanged after the chunking refactor: _chunk_input short-circuits for any
    MagicMock tokenizer (len returns 0 <= 512), so the single chunk is passed
    to the pipeline call, which raises.
    """
    mock_pipe = MagicMock(side_effect=RuntimeError("model unavailable"))
    mock_pipe.tokenizer = MagicMock()
    mock_pipe.tokenizer.return_value = {"input_ids": []}
    pg_module._pipeline = mock_pipe

    rail = PromptGuard2Rail()
    with pytest.raises(RuntimeError):
        rail.check("hello", {})
