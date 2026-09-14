"""Consumer entry point: wires RagEventConsumer -> FlashJudge -> JudgeVerdictProducer.

Run with:
    python -m finsentry.consumer.main

Environment variables:
    KAFKA_BOOTSTRAP_SERVERS   (default: localhost:9092)
    KAFKA_TOPIC               (default: rag-responses)
    KAFKA_CONSUMER_GROUP      (default: finsentry-rag-flash-judge)
    KAFKA_VERDICT_TOPIC       (default: judge-verdicts)
    GEMINI_MODE               (default: disabled)
    GEMINI_MODEL              (default: gemini-3.6-flash)
    GOOGLE_CLOUD_PROJECT
    GOOGLE_CLOUD_LOCATION     (default: global)
    GEMINI_API_KEY
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from finsentry.consumer.rag_event_consumer import RagEventConsumer
from finsentry.events.schema import RagResponseEvent
from finsentry.events.topics import (
    DEFAULT_CONSUMER_GROUP,
    JUDGE_VERDICTS_TOPIC,
    RAG_RESPONSES_TOPIC,
)
from finsentry.judges.flash_judge import JudgeVerdictProducer, flash_judge_from_env

log = logging.getLogger(__name__)


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic = os.getenv("KAFKA_TOPIC", RAG_RESPONSES_TOPIC)
    group = os.getenv("KAFKA_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP)
    verdict_topic = os.getenv("KAFKA_VERDICT_TOPIC", JUDGE_VERDICTS_TOPIC)

    judge = flash_judge_from_env()
    verdict_producer = JudgeVerdictProducer(bootstrap_servers=bootstrap, topic=verdict_topic)
    consumer = RagEventConsumer(bootstrap_servers=bootstrap, topic=topic, group_id=group)

    await verdict_producer.start()

    async def _handle(event: RagResponseEvent) -> None:
        verdict = await judge.evaluate(event)
        await verdict_producer.emit(verdict)
        log.info(
            "FlashJudge verdict emitted: app_trace_id=%s faith=%.2f ar=%.2f cr=%.2f",
            event.app_trace_id,
            verdict.faithfulness_score or 0.0,
            verdict.answer_relevance_score or 0.0,
            verdict.context_relevance_score or 0.0,
        )

    consumer.set_handler(_handle)

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("Shutdown signal received — stopping consumer")
        asyncio.create_task(consumer.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    await consumer.start()
    log.info("Consumer started — waiting for events")
    await consumer.run()
    await verdict_producer.stop()
    log.info("Consumer exited cleanly")


if __name__ == "__main__":
    asyncio.run(_run())
