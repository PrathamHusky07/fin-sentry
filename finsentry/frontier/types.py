"""
Frontier evaluation plane domain contract.

These are plain dataclasses, not Pydantic models, deliberately: the frontier
plane is an evaluation layer that reads RagResponseEvent and JudgeVerdictEvent
(both Pydantic, in finsentry/events/schema.py) but does not extend either. The
Literal-typed fields below are not enforced by the dataclass machinery itself,
so each one is validated in __post_init__ against its allowed value set —
callers get a ValueError at construction time, not a silent bad value that
surfaces three hops downstream in a materialized view.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

JudgeStatus = Literal["success", "timeout", "model_error", "unavailable"]
_JUDGE_STATUS_VALUES = set(get_args(JudgeStatus))

JudgeHealthStatus = Literal["healthy", "degraded", "unavailable"]
_JUDGE_HEALTH_STATUS_VALUES = set(get_args(JudgeHealthStatus))

FrontierVerdict = Literal[
    "frontier_pass",
    "frontier_fail",
    "frontier_uncertain",
    "disagreement_review_needed",
    "frontier_degraded",
    "frontier_unavailable",
]
_FRONTIER_VERDICT_VALUES = set(get_args(FrontierVerdict))

DisagreementClassification = Literal[
    "agreement", "mild_disagreement", "strong_disagreement", "insufficient_judges"
]
_DISAGREEMENT_CLASSIFICATION_VALUES = set(get_args(DisagreementClassification))


@dataclass
class Citation:
    chunk_id: str
    quote: str
    retrieved_text: str


@dataclass
class FrontierEvaluationInput:
    """Everything a FrontierJudge needs to evaluate one RAG interaction.

    Built by the frontier consumer from a sampled RagResponseEvent; carries no
    reference back to the event itself so judges stay decoupled from the
    Kafka envelope.
    """

    app_trace_id: str
    question: str
    answer: str
    citations: list[Citation]
    retrieved_context_chunks: list[str]
    original_rag_event_ts: str


@dataclass
class JudgeResult:
    """One judge's verdict on one FrontierEvaluationInput.

    judge_id/judge_family/methodology identify which judge produced this —
    the orchestrator never collapses judges into an average, so identity
    travels with every score.
    """

    judge_id: str
    judge_family: str
    methodology: str
    status: JudgeStatus
    faithfulness_score: float | None = None
    evidence: dict[str, Any] | None = None
    error_detail: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.status not in _JUDGE_STATUS_VALUES:
            raise ValueError(f"JudgeResult.status={self.status!r} not in {_JUDGE_STATUS_VALUES}")


@dataclass
class JudgeHealth:
    judge_id: str
    status: JudgeHealthStatus
    last_success_ts: str | None
    error_rate_1h: float

    def __post_init__(self) -> None:
        if self.status not in _JUDGE_HEALTH_STATUS_VALUES:
            raise ValueError(
                f"JudgeHealth.status={self.status!r} not in {_JUDGE_HEALTH_STATUS_VALUES}"
            )


@dataclass
class FrontierVerdictEvent:
    """Emitted to the rag-frontier-verdicts topic. One per sampled RAG event.

    The verdict is not a weighted average of per-judge scores — it is a
    classification of the per_judge_results list, with disagreement surfaced
    explicitly via disagreement_classification and score_delta rather than
    averaged away.
    """

    app_trace_id: str
    verdict: FrontierVerdict
    per_judge_results: list[JudgeResult]
    score_delta: float | None
    disagreement_classification: DisagreementClassification
    evaluation_ts: str
    frontier_sampling_decision_key: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.verdict not in _FRONTIER_VERDICT_VALUES:
            raise ValueError(
                f"FrontierVerdictEvent.verdict={self.verdict!r} not in {_FRONTIER_VERDICT_VALUES}"
            )
        if self.disagreement_classification not in _DISAGREEMENT_CLASSIFICATION_VALUES:
            raise ValueError(
                "FrontierVerdictEvent.disagreement_classification="
                f"{self.disagreement_classification!r} not in {_DISAGREEMENT_CLASSIFICATION_VALUES}"
            )

    def to_kafka_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_kafka_json(cls, payload: bytes) -> FrontierVerdictEvent:
        raw = json.loads(payload.decode("utf-8"))
        judge_results = [JudgeResult(**jr) for jr in raw.pop("per_judge_results")]
        return cls(per_judge_results=judge_results, **raw)
