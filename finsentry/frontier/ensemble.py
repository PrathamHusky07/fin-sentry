"""
Heterogeneous-judge ensemble decision contract.

decide_ensemble() is the only place the frontier plane turns N per-judge
JudgeResults into one ensemble-level outcome, and it reduces over each
judge's categorical `decision` (supported/refuted/abstain/unavailable),
never over the raw faithfulness_score. Averaging a 0.0-1.0 NLI score
(HHEM, "nli_premise_hypothesis") against a 0.0/0.5/1.0 absolute rubric
score (Gemini, "absolute_rubric_scoring") produces a number with no
defensible meaning — the two methodologies are not measuring on a shared
scale just because both happen to range over [0, 1]. See
finsentry/frontier/protocol.py for why methodology is deliberately part
of a judge's identity.

score_delta is preserved as an analysis-only field (the spread between
judges that did produce a score) for dashboards and debugging. It is
never consulted by the decision rule below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from finsentry.frontier.types import (
    DisagreementTaxonomy,
    EnsembleVerdict,
    JudgeResult,
    require_unit_interval,
)

# Imported from types.py, not redefined here: FrontierVerdictEvent and
# EnsembleOutcome share one vocabulary (see types.py's module comment on
# EnsembleVerdict for why it lives there rather than here).
_ENSEMBLE_VERDICT_VALUES = set(get_args(EnsembleVerdict))
_DISAGREEMENT_TAXONOMY_VALUES = set(get_args(DisagreementTaxonomy))


@dataclass
class EnsembleOutcome:
    """The result of reducing a list of JudgeResults to one ensemble decision.

    per_judge_results is the same list passed in, untouched — every raw
    score, decision, status, and judge identity survives into the outcome.
    Nothing about an individual judge's evidence is collapsed or discarded
    to produce verdict/disagreement_taxonomy.
    """

    verdict: EnsembleVerdict
    disagreement_taxonomy: DisagreementTaxonomy
    per_judge_results: list[JudgeResult]
    score_delta: float | None

    def __post_init__(self) -> None:
        if self.verdict not in _ENSEMBLE_VERDICT_VALUES:
            raise ValueError(
                f"EnsembleOutcome.verdict={self.verdict!r} not in {_ENSEMBLE_VERDICT_VALUES}"
            )
        if self.disagreement_taxonomy not in _DISAGREEMENT_TAXONOMY_VALUES:
            raise ValueError(
                "EnsembleOutcome.disagreement_taxonomy="
                f"{self.disagreement_taxonomy!r} not in {_DISAGREEMENT_TAXONOMY_VALUES}"
            )
        if self.score_delta is not None:
            require_unit_interval("EnsembleOutcome.score_delta", self.score_delta)


def decide_ensemble(results: list[JudgeResult]) -> EnsembleOutcome:
    """Reduce per-judge decisions to one EnsembleOutcome. Never averages scores.

    Priority order (first match wins), deliberately matching the spec this
    was built against rather than a generic voting scheme:
      1. >=2 usable (supported/refuted) judges, all supported -> agree_supported
      2. >=2 usable judges, all refuted -> agree_refuted
      3. usable judges split support vs refute -> ensemble_mixed /
         mixed_support_refute (the route-to-human-review signal)
      4. abstain is a strict majority of all returned results ->
         ensemble_abstain / abstain_dominated -- checked before the
         single-judge fallback so one confident judge cannot override an
         ensemble where most judges would not commit
      5. exactly one usable judge -> that judge's own decision / single_judge
      6. otherwise (no usable judges, abstain not a majority either --
         i.e. everything is unavailable) -> ensemble_insufficient /
         all_unavailable
    """
    total = len(results)
    scored = [r.faithfulness_score for r in results if r.faithfulness_score is not None]
    score_delta = max(scored) - min(scored) if len(scored) >= 2 else None

    supported = [r for r in results if r.decision == "supported"]
    refuted = [r for r in results if r.decision == "refuted"]
    abstained = [r for r in results if r.decision == "abstain"]
    usable = supported + refuted

    if len(usable) >= 2 and not refuted:
        return EnsembleOutcome("ensemble_supported", "agree_supported", results, score_delta)
    if len(usable) >= 2 and not supported:
        return EnsembleOutcome("ensemble_refuted", "agree_refuted", results, score_delta)
    if supported and refuted:
        return EnsembleOutcome("ensemble_mixed", "mixed_support_refute", results, score_delta)
    if total > 0 and len(abstained) > total / 2:
        return EnsembleOutcome("ensemble_abstain", "abstain_dominated", results, score_delta)
    if len(usable) == 1:
        verdict: EnsembleVerdict = (
            "ensemble_supported" if usable[0].decision == "supported" else "ensemble_refuted"
        )
        return EnsembleOutcome(verdict, "single_judge", results, score_delta)
    return EnsembleOutcome("ensemble_insufficient", "all_unavailable", results, score_delta)
