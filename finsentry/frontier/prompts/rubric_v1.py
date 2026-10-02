"""
Frontier-tier Gemini rubric prompt.

This is deliberately NOT the Flash tier's RAGAS prompt (claim extraction +
per-claim NLI verification, finsentry/judges/metrics/faithfulness_core.py).
This adapter asks for a single absolute-rubric score with structured evidence
in one call — a categorically different evaluation methodology from HHEM's
native NLI premise/hypothesis scoring, which is what makes the two judges
complementary rather than two votes on the same question.

PROMPT_VERSION is echoed back by the model in its JSON response and checked
by the adapter on every call. A mismatch (stale cached response, a future
prompt edit that forgets to bump this constant) is rejected as model_error
rather than silently accepted.
"""
from __future__ import annotations

PROMPT_VERSION = "frontier_rubric_v1"

RUBRIC_PROMPT = """\
You are evaluating whether a generated answer is faithful to its cited source \
chunks. This is absolute rubric scoring, not a comparison to a reference answer.

Question: {question}

Answer: {answer}

Cited chunks:
{cited_chunks}

Score the answer's faithfulness to the cited chunks using this rubric:
- 0.0: the answer is not supported by the cited chunks at all.
- 0.5: the answer is partially supported — some claims are grounded, others are \
not or go beyond what the chunks state.
- 1.0: the answer is fully supported by the cited chunks.

Respond with ONLY a JSON object in this exact format, no other text:
{{"prompt_version": "{prompt_version}", "faithfulness_score": 0.0 or 0.5 or 1.0, \
"rubric_reasoning": "one to two sentence justification", \
"cited_chunks_supporting": ["chunk_id", ...], \
"cited_chunks_contradicting": ["chunk_id", ...]}}"""


def build_rubric_prompt(question: str, answer: str, cited_chunks: str) -> str:
    return RUBRIC_PROMPT.format(
        question=question,
        answer=answer,
        cited_chunks=cited_chunks,
        prompt_version=PROMPT_VERSION,
    )
