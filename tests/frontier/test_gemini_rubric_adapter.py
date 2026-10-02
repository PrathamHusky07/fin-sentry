from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.prompts.rubric_v1 import PROMPT_VERSION
from finsentry.frontier.types import Citation, FrontierEvaluationInput
from finsentry.rails.output.cost_governance import CostBudget


def _evaluation_input() -> FrontierEvaluationInput:
    return FrontierEvaluationInput(
        app_trace_id="trace-1",
        question="What was Apple's total net sales in fiscal year 2024?",
        answer="Apple's total net sales in fiscal year 2024 were $391,035 million.",
        citations=[
            Citation(
                chunk_id="fecfcfbf665bb339",
                quote="Total net sales | $391,035",
                retrieved_text="Net sales disaggregated by significant products...",
            )
        ],
        retrieved_context_chunks=["Net sales disaggregated by significant products..."],
        original_rag_event_ts="2026-10-02T00:00:00+00:00",
    )


def _mock_response(
    text: str, in_tok: int = 100, out_tok: int = 20, thoughts_tok: int = 0
) -> MagicMock:
    response = MagicMock()
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response.candidates = [candidate]
    usage = MagicMock()
    usage.prompt_token_count = in_tok
    usage.candidates_token_count = out_tok
    usage.thoughts_token_count = thoughts_tok
    response.usage_metadata = usage
    return response


def _adapter_with_mocked_client(
    generate_content_return: object | None = None,
    generate_content_side_effect: object | None = None,
    cost_budget: CostBudget | None = None,
) -> GeminiRubricAdapter:
    mock_client = MagicMock()
    if generate_content_side_effect is not None:
        mock_client.models.generate_content.side_effect = generate_content_side_effect
    else:
        mock_client.models.generate_content.return_value = generate_content_return
    with patch("google.genai.Client", return_value=mock_client):
        adapter = GeminiRubricAdapter(
            cost_budget=cost_budget or CostBudget(),
            mode="vertex",
            project="test-project",
        )
    assert adapter.is_available
    return adapter


def test_successful_evaluation_parses_score_and_evidence() -> None:
    valid_response = json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "faithfulness_score": 1.0,
            "rubric_reasoning": "The answer matches the cited total net sales figure exactly.",
            "cited_chunks_supporting": ["fecfcfbf665bb339"],
            "cited_chunks_contradicting": [],
        }
    )
    adapter = _adapter_with_mocked_client(_mock_response(valid_response))

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "success"
    assert result.faithfulness_score == 1.0
    assert result.evidence is not None
    assert result.evidence["cited_chunks_supporting"] == ["fecfcfbf665bb339"]
    assert result.judge_id == "gemini-rubric"
    assert result.methodology == "absolute_rubric_scoring"


def test_malformed_response_returns_model_error() -> None:
    adapter = _adapter_with_mocked_client(_mock_response("this is not json at all"))

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "model_error"
    assert result.faithfulness_score is None


def test_timeout_returns_timeout_status() -> None:
    def _slow_call(**_kwargs: object) -> MagicMock:
        import time

        time.sleep(0.2)
        return _mock_response("{}")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = _slow_call
    with patch("google.genai.Client", return_value=mock_client):
        adapter = GeminiRubricAdapter(
            cost_budget=CostBudget(), mode="vertex", project="test-project", timeout_s=0.01
        )

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "timeout"


def test_budget_exhaustion_returns_unavailable() -> None:
    exhausted_budget = CostBudget(per_run_ceiling_usd=0.0)
    adapter = _adapter_with_mocked_client(_mock_response("{}"), cost_budget=exhausted_budget)

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "unavailable"
    assert result.error_detail == "budget_exhausted"


def test_prompt_version_mismatch_is_rejected() -> None:
    stale_response = json.dumps(
        {
            "prompt_version": "frontier_rubric_v0_stale",
            "faithfulness_score": 1.0,
            "rubric_reasoning": "stale",
            "cited_chunks_supporting": [],
            "cited_chunks_contradicting": [],
        }
    )
    adapter = _adapter_with_mocked_client(_mock_response(stale_response))

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "model_error"
    assert "prompt_version_mismatch" in (result.error_detail or "")


def test_client_not_configured_returns_unavailable() -> None:
    adapter = GeminiRubricAdapter(cost_budget=CostBudget(), mode="disabled")

    result = asyncio.run(adapter.evaluate(_evaluation_input()))

    assert result.status == "unavailable"


def test_health_check_healthy_on_successful_liveness_call() -> None:
    adapter = _adapter_with_mocked_client(_mock_response('{"status": "ok"}'))

    health = asyncio.run(adapter.health_check())

    assert health.status == "healthy"
