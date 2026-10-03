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
import math
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from finsentry.frontier.faithjudge.types import PeerRetrievalResult

JudgeStatus = Literal["success", "timeout", "model_error", "unavailable"]
_JUDGE_STATUS_VALUES = set(get_args(JudgeStatus))

JudgeDecision = Literal["supported", "refuted", "abstain", "unavailable"]
_JUDGE_DECISION_VALUES = set(get_args(JudgeDecision))

JudgeHealthStatus = Literal["healthy", "degraded", "unavailable"]
_JUDGE_HEALTH_STATUS_VALUES = set(get_args(JudgeHealthStatus))

# Day 5 M3: the heterogeneous-judge ensemble decision contract
# (finsentry/frontier/ensemble.py). Owned here, not in ensemble.py, so
# ensemble.py can import these from types.py without a circular import —
# FrontierVerdictEvent and EnsembleOutcome share one vocabulary, not two
# independently-maintained copies of it.
EnsembleVerdict = Literal[
    "ensemble_supported",
    "ensemble_refuted",
    "ensemble_mixed",
    "ensemble_abstain",
    "ensemble_insufficient",
]
_ENSEMBLE_VERDICT_VALUES = set(get_args(EnsembleVerdict))

DisagreementTaxonomy = Literal[
    "agree_supported",
    "agree_refuted",
    "mixed_support_refute",
    "abstain_dominated",
    "single_judge",
    "all_unavailable",
]
_DISAGREEMENT_TAXONOMY_VALUES = set(get_args(DisagreementTaxonomy))


def require_unit_interval(field_name: str, value: float) -> None:
    """Reject None/NaN/+-inf/out-of-range scores at the domain boundary.

    A plain dataclass does not enforce this at the type level, so every score
    that crosses into the frontier domain (judge scores, verdict deltas,
    health error rates) is checked here rather than three hops downstream in
    a materialized view or a dashboard chart.
    """
    if not math.isfinite(value) or not (0.0 <= value <= 1.0):
        raise ValueError(f"{field_name}={value!r} must be a finite float in [0.0, 1.0]")


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
    # Peer-example retrieval (FaithJudge, Day 5 M2). None when disabled or
    # not yet assembled — judges that don't use peers ignore this field.
    peer_retrieval: PeerRetrievalResult | None = None


@dataclass
class JudgeResult:
    """One judge's verdict on one FrontierEvaluationInput.

    judge_id/judge_family/methodology identify which judge produced this —
    the orchestrator never collapses judges into an average, so identity
    travels with every score.

    decision is derived evidence, never a replacement for faithfulness_score:
    each adapter maps its own raw score to supported/refuted/abstain using
    its own provisional, adapter-local thresholds (see the adapter modules),
    and the ensemble decision contract (finsentry/frontier/ensemble.py)
    reduces over these categorical decisions, not over the scores. A
    non-success status always carries decision="unavailable" — there is no
    other sensible value when a judge produced no score at all.
    """

    judge_id: str
    judge_family: str
    methodology: str
    status: JudgeStatus
    decision: JudgeDecision = "unavailable"
    faithfulness_score: float | None = None
    evidence: dict[str, Any] | None = None
    error_detail: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.status not in _JUDGE_STATUS_VALUES:
            raise ValueError(f"JudgeResult.status={self.status!r} not in {_JUDGE_STATUS_VALUES}")
        if self.decision not in _JUDGE_DECISION_VALUES:
            raise ValueError(
                f"JudgeResult.decision={self.decision!r} not in {_JUDGE_DECISION_VALUES}"
            )
        if self.status == "success":
            if self.faithfulness_score is None:
                raise ValueError("JudgeResult.faithfulness_score is required when status=success")
            require_unit_interval("JudgeResult.faithfulness_score", self.faithfulness_score)
            if self.decision == "unavailable":
                raise ValueError(
                    "JudgeResult.decision must be supported/refuted/abstain when status=success"
                )
        else:
            if self.faithfulness_score is not None:
                raise ValueError(
                    f"JudgeResult.faithfulness_score must be None when status={self.status!r}"
                )
            if self.decision != "unavailable":
                raise ValueError(
                    f"JudgeResult.decision must be unavailable when status={self.status!r}"
                )


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
        require_unit_interval("JudgeHealth.error_rate_1h", self.error_rate_1h)


@dataclass
class FrontierVerdictEvent:
    """Emitted to the rag-frontier-verdicts topic. One per sampled RAG event.

    verdict and disagreement_classification come directly from
    decide_ensemble() (finsentry/frontier/ensemble.py): a reduction over
    each judge's categorical decision, never a weighted average of
    heterogeneous judges' raw scores. score_delta is preserved as an
    analysis-only field (the spread between judges that produced a score)
    and is explicitly not the basis for verdict or disagreement_classification.

    Field names and types are unchanged from M1/M2 (verdict: str,
    disagreement_classification: str, score_delta: float | None) even
    though M3 replaced their allowed value sets — infra/risingwave/init.sql's
    source and materialized views read these as untyped VARCHAR with no
    enum constraint and never branch on a specific value, so the M3
    vocabulary change required no infra changes. Verified by reading both
    the source definition and every MV that references these columns.
    """

    app_trace_id: str
    verdict: EnsembleVerdict
    per_judge_results: list[JudgeResult]
    score_delta: float | None
    disagreement_classification: DisagreementTaxonomy
    evaluation_ts: str
    frontier_sampling_decision_key: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.verdict not in _ENSEMBLE_VERDICT_VALUES:
            raise ValueError(
                f"FrontierVerdictEvent.verdict={self.verdict!r} not in {_ENSEMBLE_VERDICT_VALUES}"
            )
        if self.disagreement_classification not in _DISAGREEMENT_TAXONOMY_VALUES:
            raise ValueError(
                "FrontierVerdictEvent.disagreement_classification="
                f"{self.disagreement_classification!r} not in {_DISAGREEMENT_TAXONOMY_VALUES}"
            )
        if self.score_delta is not None:
            require_unit_interval("FrontierVerdictEvent.score_delta", self.score_delta)

    def to_kafka_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_kafka_json(cls, payload: bytes) -> FrontierVerdictEvent:
        raw = json.loads(payload.decode("utf-8"))
        judge_results = [JudgeResult(**jr) for jr in raw.pop("per_judge_results")]
        return cls(per_judge_results=judge_results, **raw)
