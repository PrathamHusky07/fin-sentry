"""Tests for the dashboard's /traces, /traces/{id}, and /calibration/health
routes -- the Day 9 internal contracts the gateway proxies over httpx.

The fixture rows below are copied from real per_judge_results/judge_verdicts
shapes observed against the live RisingWave instance during Day 9 Phase 0
(see docs/build-log.md), not an idealized all-clean fixture: a stub-only
frontier row, a real gemini-rubric row with real reasoning text, a
blocked-before-evaluation pair, and a never-evaluated success row all
appear together, exactly as they do in the real data.
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from finsentry.dashboard.app import app
from finsentry.mcp.tools.drift import (
    DriftPolicy,
    GetDriftReportResult,
    LastHealthReading,
)

_NOW = datetime.datetime.now(datetime.UTC)

# Real row shapes, one per four-state case.
_EVALUATED_ROW = {
    "app_trace_id": "trace-evaluated",
    "timestamp_utc": _NOW,
    "endpoint": "rag",
    "ticker": "AAPL",
    "rag_status": "success",
    "judge_status": "complete",
}
_PARTIAL_ROW = {
    "app_trace_id": "trace-partial",
    "timestamp_utc": _NOW,
    "endpoint": "rag",
    "ticker": "AAPL",
    "rag_status": "success",
    "judge_status": "partial",
}
_BLOCKED_ROW = {
    "app_trace_id": "trace-blocked",
    "timestamp_utc": _NOW,
    "endpoint": "rag",
    "ticker": "AAPL",
    "rag_status": "blocked",
    "judge_status": "failed",
}
_NEVER_EVALUATED_ROW = {
    "app_trace_id": "trace-never-evaluated",
    "timestamp_utc": _NOW,
    "endpoint": "rag",
    "ticker": "AAPL",
    "rag_status": "success",
    "judge_status": None,
}

# Real per_judge_results arrays, copied verbatim from live data.
_STUB_ONLY_PER_JUDGE_RESULTS = [
    {
        "error_detail": None,
        "evidence": None,
        "faithfulness_score": 0.9,
        "judge_family": "stub",
        "judge_id": "stub-judge",
        "latency_ms": None,
        "methodology": "stub",
        "status": "success",
    }
]
_REAL_PER_JUDGE_RESULTS = [
    {
        "error_detail": None,
        "evidence": {
            "cited_chunks_contradicting": [],
            "cited_chunks_supporting": ["chunk-1"],
            "peers_used": [],
            "rubric_reasoning": (
                "The statement in the answer is verbatim supported by the retrieved context."
            ),
        },
        "faithfulness_score": 1.0,
        "judge_family": "gemini",
        "judge_id": "gemini-rubric",
        "latency_ms": 2887,
        "methodology": "absolute_rubric_scoring",
        "status": "success",
    }
]


async def _dispatch_fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if "FROM rag_events r" in sql and "LEFT JOIN judge_verdicts" in sql:
        return [_EVALUATED_ROW, _PARTIAL_ROW, _BLOCKED_ROW, _NEVER_EVALUATED_ROW]
    if "DISTINCT app_trace_id FROM rag_frontier_verdicts" in sql:
        return [{"app_trace_id": "trace-evaluated"}]
    return []


async def _dispatch_fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    if "FROM rag_events" in sql and "WHERE app_trace_id" in sql:
        trace_id = params[0]
        if trace_id == "trace-stub-only":
            return {
                "app_trace_id": trace_id,
                "status": "success",
                "endpoint": "rag",
                "ticker": "AAPL",
                "query": "q",
                "answer": "a",
                "confidence": "high",
                "model_used": "llama3.1:8b",
                "citations": [],
                "retrieved_chunk_ids": [],
                "block_reason": None,
                "block_rail": None,
                "error_kind": None,
                "error_detail": None,
                "timestamp_utc": _NOW,
            }
        if trace_id == "trace-real-judge":
            return {
                "app_trace_id": trace_id,
                "status": "success",
                "endpoint": "rag",
                "ticker": "AAPL",
                "query": "q",
                "answer": "a",
                "confidence": "high",
                "model_used": "llama3.1:8b",
                "citations": [{"chunk_id": "chunk-1", "quote": "Total net sales $391,035"}],
                "retrieved_chunk_ids": ["chunk-1"],
                "block_reason": None,
                "block_rail": None,
                "error_kind": None,
                "error_detail": None,
                "timestamp_utc": _NOW,
            }
        return None
    if "FROM judge_verdicts" in sql:
        return {
            "status": "complete",
            "timestamp_utc": _NOW,
            "faithfulness_score": 1.0,
            "faithfulness_status": "complete",
            "answer_relevance_score": 0.9,
            "answer_relevance_status": "complete",
            "context_relevance_score": 0.8,
            "context_relevance_status": "complete",
        }
    if "FROM rag_frontier_verdicts" in sql:
        trace_id = params[0]
        if trace_id == "trace-stub-only":
            return {
                "verdict": "ensemble_insufficient",
                "per_judge_results": _STUB_ONLY_PER_JUDGE_RESULTS,
                "evaluation_ts": _NOW,
            }
        if trace_id == "trace-real-judge":
            return {
                "verdict": "frontier_degraded",
                "per_judge_results": _REAL_PER_JUDGE_RESULTS,
                "evaluation_ts": _NOW,
            }
        return None
    return None


@pytest.fixture(autouse=True)
def _patch_fetch() -> Any:
    p1 = patch("finsentry.dashboard.app._fetch_all", AsyncMock(side_effect=_dispatch_fetch_all))
    p2 = patch("finsentry.dashboard.app._fetch_one", AsyncMock(side_effect=_dispatch_fetch_one))
    with p1, p2:
        yield


async def test_traces_list_exercises_all_four_judge_states() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces")

    assert resp.status_code == 200
    by_id = {t["app_trace_id"]: t for t in resp.json()["traces"]}
    assert by_id["trace-evaluated"]["judge_state"] == "evaluated"
    assert by_id["trace-partial"]["judge_state"] == "partially_evaluated"
    assert by_id["trace-blocked"]["judge_state"] == "blocked_before_evaluation"
    assert by_id["trace-never-evaluated"]["judge_state"] == "never_evaluated"
    # frontier_sampled is only true for the one trace_id the stub query returned.
    assert by_id["trace-evaluated"]["frontier_sampled"] is True
    assert by_id["trace-never-evaluated"]["frontier_sampled"] is False


async def test_trace_detail_filters_out_stub_only_frontier_row() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces/trace-stub-only")

    body = resp.json()
    assert body["found"] is True
    assert body["frontier"]["sampled"] is True
    assert body["frontier"]["evidence"] is None
    assert body["frontier"]["note"] == "frontier evaluated with no real judge recorded"


async def test_trace_detail_surfaces_real_gemini_rubric_evidence() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces/trace-real-judge")

    body = resp.json()
    assert body["frontier"]["sampled"] is True
    evidence = body["frontier"]["evidence"]
    assert evidence is not None
    assert evidence["judge_id"] == "gemini-rubric"
    assert "verbatim supported" in evidence["rubric_reasoning"]
    assert evidence["cited_chunks_supporting"] == ["chunk-1"]


async def test_trace_detail_not_found_returns_honest_state() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/traces/does-not-exist")

    body = resp.json()
    assert body["found"] is False
    assert body["judge_state"] == "never_evaluated"
    assert body["frontier"]["sampled"] is False


async def test_calibration_health_reports_position_between_thresholds() -> None:
    report = GetDriftReportResult(
        judge_id="gemini-rubric",
        policy=DriftPolicy(
            window_size=150,
            min_n=30,
            healthy_baseline_kappa=0.605,
            drift_entry_threshold=0.43,
            recovery_threshold=0.54,
            entry_consecutive_windows=3,
            recovery_consecutive_windows=5,
        ),
        last_health_reading=LastHealthReading(
            state="degraded",
            kappa=0.5161290322580646,
            window_n=30,
            committed_n=30,
            n_abstain=0,
            n_unavailable=0,
            state_as_of="2026-10-04T17:11:36.780302+00:00",
            source="docs/measurements/reliability/canary-live-smoke-d6p2.json",
        ),
        transition_history=[],
        note="reporting last-persisted state as of state_as_of",
    )
    with patch("finsentry.dashboard.app.get_drift_report", AsyncMock(return_value=report)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/calibration/health")

    body = resp.json()
    assert body["kappa"] == 0.5161290322580646
    assert body["position"] == "between_thresholds"


async def test_calibration_health_insufficient_data_when_no_reading_persisted() -> None:
    report = GetDriftReportResult(
        judge_id="gemini-rubric",
        policy=DriftPolicy(
            window_size=150,
            min_n=30,
            healthy_baseline_kappa=0.605,
            drift_entry_threshold=0.43,
            recovery_threshold=0.54,
            entry_consecutive_windows=3,
            recovery_consecutive_windows=5,
        ),
        last_health_reading=None,
        transition_history=[],
        note="no live canary health reading has been persisted yet",
    )
    with patch("finsentry.dashboard.app.get_drift_report", AsyncMock(return_value=report)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/calibration/health")

    body = resp.json()
    assert body["kappa"] is None
    assert body["position"] == "insufficient_data"
