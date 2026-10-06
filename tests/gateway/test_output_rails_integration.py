"""
Endpoint integration tests for the three-output-rail pipeline.

Each test exercises the full POST /v1/rag/query path with real SchemaEnforcementRail
and RegulatedPhraseRail instances. Only FaithfulnessRail.check is mocked (zero-cost).
This proves the three-rail pipeline is genuinely wired end-to-end, not merely tested
in isolation.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

import finsentry.gateway.main as gw
from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.main import RetrievedChunk, app
from finsentry.rails.base import RailDecision
from finsentry.rails.output.guardrails_schema import SchemaEnforcementRail
from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def breaker() -> AsyncCircuitBreaker:
    return AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="integ-rag")


@pytest.fixture()
def embed_model() -> MagicMock:
    model = MagicMock()
    model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    return model


def _chunk(chunk_id: str = "abc123") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        ticker="AAPL",
        filing_type="10-K",
        filing_date="2024-09-30",
        text="Apple reported strong revenue.",
        similarity_score=0.90,
    )


def _valid_rag_json(chunk_id: str = "abc123", answer: str = "Revenue was strong.") -> str:
    return json.dumps({
        "answer": answer,
        "citations": [{"chunk_id": chunk_id, "quote": "Apple reported strong revenue."}],
        "confidence": "high",
    })


def _faith_pass() -> MagicMock:
    rail = MagicMock()
    rail.check = AsyncMock(return_value=RailDecision(
        outcome="pass",
        reason="faithfulness check passed",
        details={
            "faithfulness_status": "passed",
            "score": 1.0,
            "supported_claims": ["Revenue was strong."],
            "unsupported_claims": [],
            "gemini_calls": 2,
            "input_tokens": 200,
            "output_tokens": 80,
            "thoughts_tokens": 120,
            "cost": {
                "run_total_usd": 0.001,
                "day_total_usd": 0.001,
                "call_count": 2,
                "prompt_tokens_total": 200,
                "candidates_tokens_total": 80,
                "thoughts_tokens_total": 120,
                "ceilings": {"per_call_usd": 0.02, "per_run_usd": 5.0, "per_day_usd": 25.0},
            },
        },
    ))
    return rail


def _faith_block() -> MagicMock:
    rail = MagicMock()
    rail.check = AsyncMock(return_value=RailDecision(
        outcome="block",
        reason="low_faithfulness",
        details={
            "faithfulness_status": "blocked",
            "score": 0.2,
            "threshold": 0.7,
            "supported_claims": [],
            "unsupported_claims": ["Revenue was strong."],
            "gemini_calls": 2,
            "input_tokens": 200,
            "output_tokens": 80,
            "thoughts_tokens": 0,
            "cost": {
                "run_total_usd": 0.001,
                "day_total_usd": 0.001,
                "call_count": 2,
                "prompt_tokens_total": 200,
                "candidates_tokens_total": 80,
                "thoughts_tokens_total": 0,
                "ceilings": {"per_call_usd": 0.02, "per_run_usd": 5.0, "per_day_usd": 25.0},
            },
        },
    ))
    return rail


def _faith_evaluator_error() -> MagicMock:
    rail = MagicMock()
    rail.check = AsyncMock(return_value=RailDecision(
        outcome="pass",
        reason="faithfulness fail-open: skipped_evaluator_error",
        details={
            "faithfulness_status": "skipped_evaluator_error",
            "sub_reason": "verdict_parse_failure",
            "gemini_calls": 1,
            "input_tokens": 100,
            "output_tokens": 20,
            "thoughts_tokens": 0,
            "cost": {
                "run_total_usd": 0.0001,
                "day_total_usd": 0.0001,
                "call_count": 1,
                "prompt_tokens_total": 100,
                "candidates_tokens_total": 20,
                "thoughts_tokens_total": 0,
                "ceilings": {"per_call_usd": 0.02, "per_run_usd": 5.0, "per_day_usd": 25.0},
            },
        },
    ))
    return rail


def _base_patches(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
    chunks: list[RetrievedChunk],
    downstream_response: str,
    faith_rail: MagicMock,
) -> list[object]:
    return [
        patch.object(gw, "_DOWNSTREAM_URL", "http://fake-llm"),
        patch.object(gw, "_DATABASE_URL", "postgresql://fake"),
        patch.object(gw, "_embed_model", embed_model),
        patch.object(gw, "_rag_breaker", breaker),
        patch.object(gw, "_adapter", None),
        patch.object(gw, "_retrieval_rail", None),
        patch.object(gw, "_schema_rail", SchemaEnforcementRail()),
        patch.object(gw, "_phrase_rail", RegulatedPhraseRail()),
        patch.object(gw, "_faithfulness_rail", faith_rail),
        patch("finsentry.gateway.main._fetch_chunks", AsyncMock(return_value=chunks)),
        patch("finsentry.gateway.main._call_downstream_rag",
              AsyncMock(return_value=downstream_response)),
    ]


# ---------------------------------------------------------------------------
# Test A: happy path — all rails pass
# ---------------------------------------------------------------------------


async def test_endpoint_all_output_rails_pass_returns_200_with_trace(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Valid downstream JSON + clean answer + mocked faith pass → 200 with all three rails."""
    chunks = [_chunk("abc123")]
    patches = _base_patches(breaker, embed_model, chunks, _valid_rag_json("abc123"), _faith_pass())

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "What was revenue?"})

    assert resp.status_code == 200
    trace = resp.json()["output_rail_trace"]
    assert "schema-enforcement" in trace
    assert trace["schema-enforcement"]["outcome"] == "pass"
    assert "regulated-phrases" in trace
    assert trace["regulated-phrases"]["outcome"] == "pass"
    assert "faithfulness" in trace
    assert trace["faithfulness"]["faithfulness_status"] == "passed"


# ---------------------------------------------------------------------------
# Test B: malformed downstream JSON → schema rail blocks
# ---------------------------------------------------------------------------


async def test_endpoint_malformed_downstream_json_returns_422_schema_rail(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Downstream returns unparseable text → 422, rail='schema-enforcement'."""
    chunks = [_chunk("abc123")]
    patches = _base_patches(
        breaker, embed_model, chunks, "not json at all", _faith_pass()
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["rail"] == "schema-enforcement"
    assert body["reason"] == "malformed_json"


# ---------------------------------------------------------------------------
# Test C: hallucinated citation → schema rail blocks
# ---------------------------------------------------------------------------


async def test_endpoint_hallucinated_citation_returns_422_schema_rail(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Downstream cites chunk_id not in retrieved set → 422, reason=hallucinated_citation."""
    chunks = [_chunk("abc123")]
    # Citation references "unknown-id", not "abc123"
    downstream = _valid_rag_json("unknown-id")
    patches = _base_patches(breaker, embed_model, chunks, downstream, _faith_pass())

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["rail"] == "schema-enforcement"
    assert body["reason"] == "hallucinated_citation"


# ---------------------------------------------------------------------------
# Test D: schema-rail-block logging never carries raw model output by default
# (Day 9 Session 2B -- the DEV_DIAGNOSTIC_LOGS gate)
# ---------------------------------------------------------------------------


async def test_schema_rail_block_log_has_no_raw_snippet_by_default(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reliability/compliance platform must not log raw model output on
    the default request path. DEV_DIAGNOSTIC_LOGS unset (the default, and
    the demo configuration) means the schema_rail_block warning carries
    only the non-sensitive diagnostic (reason, length, app_trace_id) -- the
    raw downstream body never appears in the message or in `extra`."""
    chunks = [_chunk("abc123")]
    raw_body = "not json at all -- distinctive-marker-f1n53ntry-9b2c"
    patches = _base_patches(breaker, embed_model, chunks, raw_body, _faith_pass())

    with (
        patch.object(gw, "_DEV_DIAGNOSTIC_LOGS", False),
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patches[9],
        patches[10],
        caplog.at_level(logging.WARNING, logger="finsentry.gateway.main"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 422
    block_records = [r for r in caplog.records if "schema_rail_block" in r.getMessage()]
    assert block_records, "expected a schema_rail_block warning log record"
    for record in block_records:
        assert raw_body not in record.getMessage()
        assert not hasattr(record, "raw_ollama_response_snippet")
    assert "malformed_json" in block_records[0].getMessage()
    assert "app_trace_id=" in block_records[0].getMessage()


async def test_schema_rail_block_log_includes_raw_snippet_when_dev_flag_set(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The inverse of the test above: with DEV_DIAGNOSTIC_LOGS explicitly
    set, the raw snippet is still available for local debugging -- the gate
    controls the default, not the capability."""
    chunks = [_chunk("abc123")]
    raw_body = "not json at all -- distinctive-marker-f1n53ntry-9b2c"
    patches = _base_patches(breaker, embed_model, chunks, raw_body, _faith_pass())

    with (
        patch.object(gw, "_DEV_DIAGNOSTIC_LOGS", True),
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patches[8],
        patches[9],
        patches[10],
        caplog.at_level(logging.WARNING, logger="finsentry.gateway.main"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 422
    block_records = [r for r in caplog.records if "schema_rail_block" in r.getMessage()]
    assert block_records, "expected a schema_rail_block warning log record"
    assert raw_body in block_records[0].getMessage()


# ---------------------------------------------------------------------------
# Test D: regulated phrase in answer → phrase rail blocks
# ---------------------------------------------------------------------------


async def test_endpoint_regulated_phrase_in_answer_returns_422_phrase_rail(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Answer contains 'guaranteed returns' → 422, rail='regulated-phrases'."""
    chunks = [_chunk("abc123")]
    downstream = json.dumps({
        "answer": "This investment offers guaranteed returns every year.",
        "citations": [{"chunk_id": "abc123", "quote": "Apple reported strong revenue."}],
        "confidence": "high",
    })
    patches = _base_patches(breaker, embed_model, chunks, downstream, _faith_pass())

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Investment advice?"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["rail"] == "regulated-phrases"


# ---------------------------------------------------------------------------
# Test E: low faithfulness → faithfulness rail blocks
# ---------------------------------------------------------------------------


async def test_endpoint_low_faithfulness_returns_422_faithfulness_rail(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Mocked faithfulness returns block → 422, rail='faithfulness'."""
    chunks = [_chunk("abc123")]
    patches = _base_patches(
        breaker, embed_model, chunks, _valid_rag_json("abc123"), _faith_block()
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["rail"] == "faithfulness"
    assert body["reason"] == "low_faithfulness"


# ---------------------------------------------------------------------------
# Test F: faithfulness evaluator error → 200 with annotated trace
# ---------------------------------------------------------------------------


async def test_endpoint_faithfulness_evaluator_error_returns_200_with_annotation(
    breaker: AsyncCircuitBreaker,
    embed_model: MagicMock,
) -> None:
    """Evaluator error (fail-open) → 200, trace faithfulness_status=skipped_evaluator_error."""
    chunks = [_chunk("abc123")]
    patches = _base_patches(
        breaker, embed_model, chunks, _valid_rag_json("abc123"), _faith_evaluator_error()
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/rag/query", json={"query": "Revenue?"})

    assert resp.status_code == 200
    trace = resp.json()["output_rail_trace"]
    assert "faithfulness" in trace
    assert trace["faithfulness"]["faithfulness_status"] == "skipped_evaluator_error"
