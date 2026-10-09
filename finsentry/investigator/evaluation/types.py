"""
The shape of a known-answer incident case.

An investigator sees only `trigger`, `window`, `scope` and, through the adapter, `world`. The
`truth` is read by the scorer alone. Cases are synthetic: every record is built by the
fixtures module from a seeded cause, so the right answer is known and no production data,
model call or mutation is involved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from finsentry.investigator.contracts import (
    AffectedScope,
    EvidenceRef,
    IncidentTrigger,
    StoppingReason,
    Subsystem,
    TimeWindow,
    ToolName,
)
from finsentry.investigator.evaluation.world import WorldData


def canonical(value: object) -> object:
    """A JSON-ready form with a fixed order, so equal cases always hash equal."""
    if isinstance(value, BaseModel):
        return canonical(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: canonical(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, set | frozenset):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, list | tuple):
        return [canonical(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


IncidentClass = Literal[
    "judge_degradation",
    "bad_retrieval_chunk",
    "injection_surge",
    "guardrail_regression",
    "mixed_multi_subsystem",
    "misleading_symptom",
    "insufficient_evidence",
]


@dataclass(frozen=True)
class GroundTruth:
    expected_outcome: Literal["diagnosis", "abstention"]
    # The subsystems that hold the seeded cause. Empty when abstention is the right answer.
    true_subsystems: frozenset[Subsystem] = frozenset()
    # Where the visible symptom points, when that is not where the cause is.
    symptom_subsystem: Subsystem | None = None
    # Identifiers a correct explanation names (a chunk id, a judge id).
    cause_markers: tuple[str, ...] = ()
    # Records a good investigation retrieves and cites as support.
    required_evidence: tuple[EvidenceRef, ...] = ()
    # Records that cut against the tempting wrong hypothesis and should be recorded.
    contradicting_required: tuple[EvidenceRef, ...] = ()
    # A minimal sequence of queries that retrieves the required evidence.
    recipe: tuple[tuple[ToolName, dict[str, object]], ...] = ()
    min_tool_calls: int = 0
    acceptable_scenarios: frozenset[str] = frozenset()
    acceptable_tools: frozenset[ToolName] = frozenset()
    acceptable_stops: frozenset[StoppingReason] = frozenset()


@dataclass(frozen=True)
class IncidentCase:
    case_id: str
    incident_class: IncidentClass
    description: str
    trigger: IncidentTrigger
    window: TimeWindow
    world: WorldData
    truth: GroundTruth
    scope: AffectedScope = field(default_factory=AffectedScope)

    def fingerprint(self) -> str:
        """A hash of everything that defines the case, so a recorded run names its inputs."""
        parts = canonical(
            [self.case_id, self.trigger, self.window, self.scope, self.world, self.truth]
        )
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]
