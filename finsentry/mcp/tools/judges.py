"""
get_judge_scores: every judge_verdicts row for one request. Surfaces both
flash-tier and frontier-tier verdicts when present -- judge_tier
distinguishes them, both land in the same source. Scoped to judge_verdicts
only (explicit Day 7 scope decision): no rag_frontier_verdicts ensemble
enrichment in this tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from finsentry.mcp._util import iso
from finsentry.mcp.state import dao, read_rows


@dataclass
class JudgeVerdict:
    judge_tier: str
    judge_model: str
    status: str
    timestamp_utc: str | None
    faithfulness_score: float | None
    faithfulness_status: str | None
    answer_relevance_score: float | None
    answer_relevance_status: str | None
    context_relevance_score: float | None
    context_relevance_status: str | None
    total_input_tokens: int
    total_output_tokens: int
    total_thoughts_tokens: int
    total_gemini_calls: int
    total_cost_usd: float
    evaluation_latency_ms: int


@dataclass
class GetJudgeScoresResult:
    app_trace_id: str
    verdicts: list[JudgeVerdict]
    count: int
    risingwave_connected: bool


async def get_judge_scores(app_trace_id: str) -> GetJudgeScoresResult:
    """Return every judge_verdicts row for one request: flash-tier and
    frontier-tier scores and statuses, token usage, and cost, in arrival
    order. Source: judge_verdicts (judge_tier field distinguishes flash
    vs frontier -- both tiers emit to the same event stream)."""
    rows = await read_rows(
        """
        SELECT judge_tier, judge_model, status, timestamp_utc,
               faithfulness_score, faithfulness_status,
               answer_relevance_score, answer_relevance_status,
               context_relevance_score, context_relevance_status,
               total_input_tokens, total_output_tokens, total_thoughts_tokens,
               total_gemini_calls, total_cost_usd, evaluation_latency_ms
        FROM judge_verdicts
        WHERE app_trace_id = %s
        ORDER BY timestamp_utc ASC
        """,
        (app_trace_id,),
    )
    verdicts = [
        JudgeVerdict(
            judge_tier=r["judge_tier"],
            judge_model=r["judge_model"],
            status=r["status"],
            timestamp_utc=iso(r["timestamp_utc"]),
            faithfulness_score=r["faithfulness_score"],
            faithfulness_status=r["faithfulness_status"],
            answer_relevance_score=r["answer_relevance_score"],
            answer_relevance_status=r["answer_relevance_status"],
            context_relevance_score=r["context_relevance_score"],
            context_relevance_status=r["context_relevance_status"],
            total_input_tokens=r["total_input_tokens"],
            total_output_tokens=r["total_output_tokens"],
            total_thoughts_tokens=r["total_thoughts_tokens"],
            total_gemini_calls=r["total_gemini_calls"],
            total_cost_usd=r["total_cost_usd"],
            evaluation_latency_ms=r["evaluation_latency_ms"],
        )
        for r in rows
    ]
    return GetJudgeScoresResult(
        app_trace_id=app_trace_id,
        verdicts=verdicts,
        count=len(verdicts),
        risingwave_connected=dao.connected,
    )
