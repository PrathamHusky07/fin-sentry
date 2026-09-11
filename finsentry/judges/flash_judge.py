"""
FlashJudge: async quality evaluator that runs three metrics on each
RagResponseEvent and emits a JudgeVerdictEvent.

Metrics (all fail-open):
  - Faithfulness (Es et al. 2023 via faithfulness_core)
  - Answer Relevance (Zheng-bias-guarded)
  - Context Relevance (Zheng-bias-guarded, per-chunk mean)

Architecture:
  - FlashJudge.evaluate() is the entry point; the consumer calls it.
  - It uses a shared CostBudget per-call (not per-session) so each evaluation
    has its own budget and a slow/expensive event does not starve the next one.
  - The Gemini client is optional; when mode="disabled" all metrics return
    skipped_no_key so the consumer can run without credentials.
  - JudgeVerdictProducer wraps an aiokafka producer for emit; it is injectable
    for testing so tests never touch a real Kafka broker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from finsentry.events.schema import JudgeVerdictEvent, RagResponseEvent
from finsentry.judges.metrics.answer_relevance import evaluate_answer_relevance
from finsentry.judges.metrics.context_relevance import evaluate_context_relevance
from finsentry.judges.metrics.faithfulness_core import (
    GenerateFn,
    make_gemini_generate_fn,
)
from finsentry.judges.metrics.faithfulness_core import (
    evaluate_faithfulness as _eval_faithfulness,
)
from finsentry.rails.output.cost_governance import CostBudget

log = logging.getLogger(__name__)

_FLASH_MODEL = "gemini-2.5-flash"


class JudgeVerdictProducer:
    """Thin wrapper around an aiokafka producer for JudgeVerdictEvent.

    inject_producer() replaces the underlying producer for unit tests.
    """

    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: Any = None

    def inject_producer(self, producer: Any) -> None:
        self._producer = producer

    async def start(self) -> None:
        if self._producer is None:
            from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

            self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def emit(self, verdict: JudgeVerdictEvent) -> None:
        if self._producer is None:
            log.warning("JudgeVerdictProducer: not started, dropping verdict %s", verdict.event_id)
            return
        try:
            await self._producer.send_and_wait(
                self._topic,
                value=verdict.to_kafka_json(),
                key=verdict.app_trace_id.encode(),
            )
        except Exception:
            log.exception("JudgeVerdictProducer: failed to emit verdict %s", verdict.event_id)


class FlashJudge:
    """Orchestrates Faithfulness + AnswerRelevance + ContextRelevance per event.

    Each call to evaluate() uses a fresh CostBudget so per-request cost is
    bounded independently of other concurrent evaluations.
    """

    def __init__(
        self,
        mode: str = "disabled",
        model_name: str = _FLASH_MODEL,
        project: str | None = None,
        location: str = "global",
        api_key: str | None = None,
    ) -> None:
        self._mode = mode
        self._model_name = model_name
        self._client: Any = None

        if mode == "disabled":
            return

        from google import genai

        if mode == "vertex":
            if not project:
                log.error("FlashJudge vertex mode requires GOOGLE_CLOUD_PROJECT")
                self._mode = "disabled"
                return
            self._client = genai.Client(vertexai=True, project=project, location=location)
        elif mode == "developer":
            if not api_key:
                log.error("FlashJudge developer mode requires GEMINI_API_KEY")
                self._mode = "disabled"
                return
            self._client = genai.Client(api_key=api_key)
        else:
            log.error("FlashJudge unknown mode %r — disabling", mode)
            self._mode = "disabled"

    def _make_generate_fn(self) -> GenerateFn | None:
        if self._client is None:
            return None
        return make_gemini_generate_fn(self._client, self._model_name)

    async def evaluate(self, event: RagResponseEvent) -> JudgeVerdictEvent:
        """Run all three metrics on event and return a JudgeVerdictEvent."""
        budget = CostBudget()
        generate_fn = self._make_generate_fn()

        faithfulness_score: float | None = None
        faithfulness_status: str | None = None
        answer_relevance_score: float | None = None
        answer_relevance_status: str | None = None
        context_relevance_score: float | None = None
        context_relevance_status: str | None = None
        total_in = total_out = total_thoughts = total_calls = 0

        if generate_fn is None:
            faithfulness_status = "skipped_no_key"
            answer_relevance_status = "skipped_no_key"
            context_relevance_status = "skipped_no_key"
        else:
            # Only score success events that have answer + context
            if event.status == "success" and event.answer:
                faith_result, ar_result, cr_result = await asyncio.gather(
                    _eval_faithfulness(
                        answer_text=event.answer,
                        chunk_texts=event.retrieved_chunks_text,
                        generate_fn=generate_fn,
                        cost_budget=budget,
                    ),
                    evaluate_answer_relevance(
                        question=event.query,
                        answer_text=event.answer,
                        generate_fn=generate_fn,
                        cost_budget=budget,
                    ),
                    evaluate_context_relevance(
                        question=event.query,
                        chunk_texts=event.retrieved_chunks_text,
                        generate_fn=generate_fn,
                        cost_budget=budget,
                    ),
                    return_exceptions=True,
                )

                if isinstance(faith_result, BaseException):
                    log.exception("FlashJudge: faithfulness error for %s", event.app_trace_id)
                    faithfulness_status = "skipped_evaluator_error"
                else:
                    is_complete = faith_result.status == "complete"
                    faithfulness_score = faith_result.score if is_complete else None
                    faithfulness_status = faith_result.status
                    total_in += faith_result.total_input_tokens
                    total_out += faith_result.total_output_tokens
                    total_thoughts += faith_result.total_thoughts_tokens
                    total_calls += faith_result.total_gemini_calls

                if isinstance(ar_result, BaseException):
                    log.exception("FlashJudge: answer_relevance error for %s", event.app_trace_id)
                    answer_relevance_status = "skipped_evaluator_error"
                else:
                    ar_complete = ar_result.status == "complete"
                    answer_relevance_score = ar_result.score if ar_complete else None
                    answer_relevance_status = ar_result.status
                    total_in += ar_result.total_input_tokens
                    total_out += ar_result.total_output_tokens
                    total_thoughts += ar_result.total_thoughts_tokens
                    total_calls += ar_result.total_gemini_calls

                if isinstance(cr_result, BaseException):
                    log.exception("FlashJudge: context_relevance error for %s", event.app_trace_id)
                    context_relevance_status = "skipped_evaluator_error"
                else:
                    cr_complete = cr_result.status == "complete"
                    context_relevance_score = cr_result.score if cr_complete else None
                    context_relevance_status = cr_result.status
                    total_in += cr_result.total_input_tokens
                    total_out += cr_result.total_output_tokens
                    total_thoughts += cr_result.total_thoughts_tokens
                    total_calls += cr_result.total_gemini_calls
            else:
                faithfulness_status = "skipped_non_success"
                answer_relevance_status = "skipped_non_success"
                context_relevance_status = "skipped_non_success"

        return JudgeVerdictEvent(
            event_id=str(uuid.uuid4()),
            source_event_id=event.event_id,
            app_trace_id=event.app_trace_id,
            timestamp_utc=datetime.now(UTC).isoformat(),
            faithfulness_score=faithfulness_score,
            faithfulness_status=faithfulness_status,
            answer_relevance_score=answer_relevance_score,
            answer_relevance_status=answer_relevance_status,
            context_relevance_score=context_relevance_score,
            context_relevance_status=context_relevance_status,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_thoughts_tokens=total_thoughts,
            total_gemini_calls=total_calls,
        )


def flash_judge_from_env() -> FlashJudge:
    """Build a FlashJudge from environment variables."""
    mode = os.getenv("GEMINI_MODE", "disabled")
    return FlashJudge(
        mode=mode,
        model_name=os.getenv("GEMINI_MODEL", _FLASH_MODEL),
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        api_key=os.getenv("GEMINI_API_KEY"),
    )
