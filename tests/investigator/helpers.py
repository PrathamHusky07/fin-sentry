"""Shared builders for the investigator tests."""

from __future__ import annotations

from finsentry.investigator.contracts import (
    Hypothesis,
    IncidentTrigger,
    InvestigationState,
    PredictedObservation,
    TimeWindow,
)
from finsentry.investigator.fixtures import ANCHOR, at


def make_state(incident_id: str = "inc-1", **overrides: object) -> InvestigationState:
    fields: dict[str, object] = {
        "incident_id": incident_id,
        "trigger": IncidentTrigger(
            kind="faithfulness_block_cluster", description="blocks rose on AAPL"
        ),
        "window": TimeWindow(start=at(60), end=ANCHOR),
    }
    fields.update(overrides)
    return InvestigationState.model_validate(fields)


def make_hypothesis(hypothesis_id: str = "h1", **overrides: object) -> Hypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": hypothesis_id,
        "statement": "a retrieved chunk is stale",
        "subsystem": "retrieval",
        "predicted_observations": [
            PredictedObservation(tool="search_traces", description="blocked traces share a chunk")
        ],
    }
    fields.update(overrides)
    return Hypothesis.model_validate(fields)
