"""
Vertex Gemini rubric frontier judge adapter.

Reuses the Vertex client construction pattern from FlashJudge
(finsentry/judges/flash_judge.py) — same genai.Client(vertexai=True, ...)
call, zero new Google Cloud configuration. Does not import from the Flash
tier: the frontier prompt, response shape, and status vocabulary are all
different, and Flash tier code is read-only from here per the M1 scope.

Methodology: absolute rubric scoring over a single faithfulness_to_citations
dimension, with structured evidence capture in one call. See
finsentry/frontier/prompts/rubric_v1.py for why this differs from HHEM's
native NLI methodology.

Prompt version: uses rubric_v2_faithjudge for every call (peers or no
peers) — see finsentry/frontier/prompts/rubric_v2_faithjudge.py. rubric_v1
stays in the repo frozen for historical reproducibility of verdicts
emitted before Day 5 M2; this adapter no longer calls it.

Budget: the caller owns the CostBudget instance (persists across events for
the life of the frontier consumer process) and passes it in. This adapter
does not create its own budget and does not reach into the Flash tier's
per-event budget, which is ephemeral and not actually shared across events.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

from finsentry.frontier.prompts.rubric_v2_faithjudge import PROMPT_VERSION, build_rubric_prompt
from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult
from finsentry.rails.output.cost_governance import CostBudget

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30.0
_LIVENESS_PROMPT = (
    'Respond with ONLY this exact JSON object, no other text: {"status": "ok"}'
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class GeminiRubricAdapter:
    judge_id = "gemini-rubric"
    judge_family = "gemini"
    methodology = "absolute_rubric_scoring"

    def __init__(
        self,
        cost_budget: CostBudget,
        mode: str = "disabled",
        model_name: str = "gemini-3.6-flash",
        project: str | None = None,
        location: str = "global",
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._cost_budget = cost_budget
        self._mode = mode
        self._model_name = model_name
        self._timeout_s = timeout_s
        self._client: Any = None

        if mode == "disabled":
            return

        from google import genai

        if mode == "vertex":
            if not project:
                log.error("GeminiRubricAdapter vertex mode requires GOOGLE_CLOUD_PROJECT")
                self._mode = "disabled"
                return
            self._client = genai.Client(vertexai=True, project=project, location=location)
        elif mode == "developer":
            if not api_key:
                log.error("GeminiRubricAdapter developer mode requires GEMINI_API_KEY")
                self._mode = "disabled"
                return
            self._client = genai.Client(api_key=api_key)
        else:
            log.error("GeminiRubricAdapter unknown mode %r — disabling", mode)
            self._mode = "disabled"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _call_gemini(self, prompt: str) -> tuple[str, int, int, int]:
        response = self._client.models.generate_content(model=self._model_name, contents=prompt)
        text = ""
        if response.candidates:
            first = response.candidates[0]
            if first.content and first.content.parts:
                text = first.content.parts[0].text or ""
        usage = response.usage_metadata
        in_tok = usage.prompt_token_count or 0 if usage else 0
        out_tok = usage.candidates_token_count or 0 if usage else 0
        thoughts_tok = usage.thoughts_token_count or 0 if usage else 0
        return text, in_tok, out_tok, thoughts_tok

    def _estimate_next_call_cost(self) -> float:
        report = self._cost_budget.report()
        count = report["call_count"]
        return report["run_total_usd"] / count if count > 0 else 0.001

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        if self._client is None:
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="unavailable",
                error_detail="gemini client not configured",
            )

        allowed, ceiling_reason = self._cost_budget.can_proceed(self._estimate_next_call_cost())
        if not allowed:
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="unavailable",
                error_detail="budget_exhausted",
            )

        peers = (
            evaluation_input.peer_retrieval.peers if evaluation_input.peer_retrieval else []
        )
        prompt = build_rubric_prompt(
            question=evaluation_input.question,
            answer=evaluation_input.answer,
            retrieved_context_chunks=evaluation_input.retrieved_context_chunks,
            citations=evaluation_input.citations,
            peers=peers,
        )

        start = time.monotonic()
        try:
            text, in_tok, out_tok, thoughts_tok = await asyncio.wait_for(
                asyncio.to_thread(self._call_gemini, prompt), timeout=self._timeout_s
            )
        except TimeoutError:
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="timeout",
                error_detail=f"evaluate() exceeded {self._timeout_s}s",
            )
        except Exception as exc:
            log.exception("GeminiRubricAdapter: Gemini call failed")
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail=str(exc)[:500],
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        self._cost_budget.record_call(in_tok, out_tok, thoughts_tok)

        try:
            parsed = json.loads(_strip_json_fences(text))
        except (json.JSONDecodeError, ValueError):
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail=f"malformed_json_response: {text[:200]!r}",
                latency_ms=latency_ms,
            )

        if not isinstance(parsed, dict):
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail="response_not_a_json_object",
                latency_ms=latency_ms,
            )

        if parsed.get("prompt_version") != PROMPT_VERSION:
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail=f"prompt_version_mismatch: {parsed.get('prompt_version')!r}",
                latency_ms=latency_ms,
            )

        try:
            score = float(parsed["faithfulness_score"])
        except (KeyError, TypeError, ValueError):
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail="missing_or_invalid_faithfulness_score",
                latency_ms=latency_ms,
            )

        if not math.isfinite(score) or not (0.0 <= score <= 1.0):
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="model_error",
                error_detail=f"faithfulness_score_out_of_range: {score!r}",
                latency_ms=latency_ms,
            )

        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status="success",
            faithfulness_score=score,
            evidence={
                "rubric_reasoning": parsed.get("rubric_reasoning"),
                "cited_chunks_supporting": parsed.get("cited_chunks_supporting", []),
                "cited_chunks_contradicting": parsed.get("cited_chunks_contradicting", []),
                "peers_used": [
                    {"example_id": p.example_id, "similarity": p.similarity} for p in peers
                ],
            },
            latency_ms=latency_ms,
        )

    async def health_check(self) -> JudgeHealth:
        if self._client is None:
            return JudgeHealth(
                judge_id=self.judge_id,
                status="unavailable",
                last_success_ts=None,
                error_rate_1h=1.0,
            )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._call_gemini, _LIVENESS_PROMPT), timeout=self._timeout_s
            )
            return JudgeHealth(
                judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
            )
        except Exception:
            return JudgeHealth(
                judge_id=self.judge_id, status="degraded", last_success_ts=None, error_rate_1h=1.0
            )
