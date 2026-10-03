"""
Evidence-contract test: every judge scores against the same authoritative
evaluation context (FrontierEvaluationInput.retrieved_context_chunks), never
a citation-filtered subset. Citations are separate metadata a judge may use
to report supporting/contradicting chunks, but must never narrow what gets
scored — see the Day 5 M2 build log for the decision.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.adapters.hhem_adapter import HHEMAdapter
from finsentry.frontier.prompts.rubric_v2_faithjudge import PROMPT_VERSION
from finsentry.frontier.types import Citation, FrontierEvaluationInput
from finsentry.rails.output.cost_governance import CostBudget

# Citation quote/retrieved_text deliberately narrower than the full context —
# if a judge scored against only the citation, this chunk would be invisible.
_UNCITED_CONTEXT_CHUNK = "Total operating expenses for fiscal 2024 were $223,546 million."
_CITED_CONTEXT_CHUNK = "Total net sales were $391,035 million in fiscal 2024."


def _evaluation_input() -> FrontierEvaluationInput:
    return FrontierEvaluationInput(
        app_trace_id="trace-evidence",
        question="What was Apple's total net sales and operating expenses in fiscal 2024?",
        answer="Net sales were $391,035 million; operating expenses were $223,546 million.",
        citations=[
            Citation(
                chunk_id="c1",
                quote="$391,035",
                retrieved_text=_CITED_CONTEXT_CHUNK,
            )
        ],
        retrieved_context_chunks=[_CITED_CONTEXT_CHUNK, _UNCITED_CONTEXT_CHUNK],
        original_rag_event_ts="2026-10-02T00:00:00+00:00",
    )


def test_hhem_scores_against_full_context_not_just_citations() -> None:
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.8]
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=mock_model,
    ):
        adapter = HHEMAdapter()

    asyncio.run(adapter.evaluate(_evaluation_input()))

    (premise, _hypothesis), *_ = mock_model.predict.call_args[0][0]
    assert _CITED_CONTEXT_CHUNK in premise
    assert _UNCITED_CONTEXT_CHUNK in premise


def test_gemini_scores_against_full_context_not_just_citations() -> None:
    response = MagicMock()
    part = MagicMock()
    part.text = json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "faithfulness_score": 1.0,
            "rubric_reasoning": "ok",
            "cited_chunks_supporting": ["c1"],
            "cited_chunks_contradicting": [],
        }
    )
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response.candidates = [candidate]
    response.usage_metadata = None

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = response
    with patch("google.genai.Client", return_value=mock_client):
        adapter = GeminiRubricAdapter(
            cost_budget=CostBudget(), mode="vertex", project="test-project"
        )

    asyncio.run(adapter.evaluate(_evaluation_input()))

    sent_prompt = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert _CITED_CONTEXT_CHUNK in sent_prompt
    assert _UNCITED_CONTEXT_CHUNK in sent_prompt


def test_both_judges_receive_the_same_evaluation_context_for_the_same_input() -> None:
    evaluation_input = _evaluation_input()

    hhem_mock_model = MagicMock()
    hhem_mock_model.predict.return_value = [0.8]
    with patch(
        "transformers.AutoModelForSequenceClassification.from_pretrained",
        return_value=hhem_mock_model,
    ):
        hhem = HHEMAdapter()
    asyncio.run(hhem.evaluate(evaluation_input))
    (hhem_premise, _), *_ = hhem_mock_model.predict.call_args[0][0]

    response = MagicMock()
    part = MagicMock()
    part.text = json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "faithfulness_score": 1.0,
            "rubric_reasoning": "ok",
            "cited_chunks_supporting": [],
            "cited_chunks_contradicting": [],
        }
    )
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response.candidates = [candidate]
    response.usage_metadata = None
    gemini_mock_client = MagicMock()
    gemini_mock_client.models.generate_content.return_value = response
    with patch("google.genai.Client", return_value=gemini_mock_client):
        gemini = GeminiRubricAdapter(
            cost_budget=CostBudget(), mode="vertex", project="test-project"
        )
    asyncio.run(gemini.evaluate(evaluation_input))
    gemini_prompt = gemini_mock_client.models.generate_content.call_args.kwargs["contents"]

    expected_context = "\n\n".join(evaluation_input.retrieved_context_chunks)
    assert hhem_premise == expected_context
    assert expected_context in gemini_prompt
