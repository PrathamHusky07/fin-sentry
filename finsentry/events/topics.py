"""Canonical Redpanda topic names and consumer group used across the async pipeline.

Centralised here so producer, consumer, lag monitor, and consumer/main all agree
on the topic names without scattered string literals. A mismatch between the
producer's topic and the consumer's topic is a silent pipeline break.
"""
from typing import Final

RAG_RESPONSES_TOPIC: Final[str] = "rag-responses"
JUDGE_VERDICTS_TOPIC: Final[str] = "judge-verdicts"
DEFAULT_CONSUMER_GROUP: Final[str] = "finsentry-rag-flash-judge"

RAG_FRONTIER_VERDICTS_TOPIC: Final[str] = "rag-frontier-verdicts"
DEFAULT_FRONTIER_CONSUMER_GROUP: Final[str] = "frontier-tier"
