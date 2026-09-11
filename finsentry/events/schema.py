"""
RagResponseEvent — the single event envelope emitted to Redpanda for every
gateway interaction (success, blocked, or error).

Design principles:
- Contract derived from RagQueryResponse and RagAnswerResponse, not invented.
  Every field either already exists in the current response or is a lifecycle /
  serving field the response doesn't carry.
- schema_version="1.0" from day one. Consumers must skip unrecognized versions
  (log at WARNING, drop the event; do not crash).
- Self-sufficient: the event carries enough for the async judge to reproduce the
  Faithfulness evaluation without calling back into the gateway.
- Single envelope with status lifecycle field ("success" | "blocked" | "error"),
  not separate event types per outcome. Enables "show everything for request X"
  via one topic scan filtered by app_trace_id.
- app_trace_id is the application-level correlation UUID, distinct from the
  OTel trace_id (a 128-bit hex value from OTel context propagation). Both may
  appear on the outer OTel span as separate attributes; the event carries only
  app_trace_id because it is stable across services that don't propagate OTel
  context.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class RagResponseEvent(BaseModel):
    schema_version: str = "1.0"
    event_id: str  # UUID4 for this event; distinct from app_trace_id
    app_trace_id: str  # matches RagQueryResponse.retrieval_trace_id for this request

    timestamp_utc: str  # ISO 8601 at emit time

    status: Literal["success", "blocked", "error"]

    # Request fields
    endpoint: str  # e.g. "/v1/rag/query"
    query: str
    ticker: str | None

    # Retrieval (populated on success; may be partial on blocked if retrieval ran)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    retrieved_chunks_text: list[str] = Field(default_factory=list)

    # Generation (populated only on status="success")
    answer: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] | None = None
    model_used: str = ""  # value of _DOWNSTREAM_MODEL_ROUTING_ID at emit time

    # Rail decisions snapshot
    input_rail_status: Literal["pass", "modified", "blocked"] = "pass"
    output_rail_trace_snapshot: dict[str, Any] = Field(default_factory=dict)
    block_reason: str | None = None  # populated when status="blocked"
    block_rail: str | None = None  # populated when status="blocked"

    # Error (populated only on status="error")
    error_kind: str | None = None
    error_detail: str | None = None

    # Serving
    total_latency_ms: int

    def to_kafka_json(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_kafka_json(cls, payload: bytes) -> RagResponseEvent:
        return cls.model_validate(json.loads(payload.decode("utf-8")))
