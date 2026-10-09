"""The known-answer suite: six diagnosis classes, one of them deliberately misleading, and
three insufficient-evidence variants."""

from __future__ import annotations

from finsentry.investigator.evaluation.cases_abstain import (
    ambiguous_signal,
    sparse_signal,
    unavailable_source,
)
from finsentry.investigator.evaluation.cases_diagnosis import (
    drifted_judge_looks_like_retrieval,
    injection_surge,
    judge_outage,
    retrieval_and_judge,
    schema_rail_regression,
    stale_chunk,
)
from finsentry.investigator.evaluation.types import IncidentCase


def all_cases() -> list[IncidentCase]:
    return [
        judge_outage(),
        stale_chunk(),
        injection_surge(),
        schema_rail_regression(),
        retrieval_and_judge(),
        drifted_judge_looks_like_retrieval(),
        unavailable_source(),
        sparse_signal(),
        ambiguous_signal(),
    ]


MISLEADING_CASE_ID = "drifted-judge-misleading"
