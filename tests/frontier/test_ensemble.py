from __future__ import annotations

from finsentry.frontier.ensemble import decide_ensemble
from finsentry.frontier.types import JudgeResult


def _result(
    judge_id: str,
    status: str = "success",
    decision: str = "unavailable",
    score: float | None = None,
) -> JudgeResult:
    return JudgeResult(
        judge_id=judge_id,
        judge_family=judge_id,
        methodology="stub",
        status=status,  # type: ignore[arg-type]
        decision=decision,  # type: ignore[arg-type]
        faithfulness_score=score,
    )


def test_two_supported_yields_agree_supported() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.9),
            _result("b", decision="supported", score=0.85),
        ]
    )
    assert outcome.verdict == "ensemble_supported"
    assert outcome.disagreement_taxonomy == "agree_supported"


def test_two_refuted_yields_agree_refuted() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="refuted", score=0.1),
            _result("b", decision="refuted", score=0.05),
        ]
    )
    assert outcome.verdict == "ensemble_refuted"
    assert outcome.disagreement_taxonomy == "agree_refuted"


def test_one_supported_one_refuted_yields_ensemble_mixed() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.9),
            _result("b", decision="refuted", score=0.1),
        ]
    )
    assert outcome.verdict == "ensemble_mixed"
    assert outcome.disagreement_taxonomy == "mixed_support_refute"


def test_abstain_dominated_two_abstains() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="abstain", score=0.5),
            _result("b", decision="abstain", score=0.45),
        ]
    )
    assert outcome.verdict == "ensemble_abstain"
    assert outcome.disagreement_taxonomy == "abstain_dominated"


def test_abstain_dominated_overrides_a_lone_decisive_judge() -> None:
    """Strict majority of abstains must win even when one judge did produce
    a usable decision -- the ordering the spec calls for explicitly."""
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.9),
            _result("b", decision="abstain", score=0.5),
            _result("c", decision="abstain", score=0.45),
        ]
    )
    assert outcome.verdict == "ensemble_abstain"
    assert outcome.disagreement_taxonomy == "abstain_dominated"


def test_single_usable_judge_supported() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.9),
            _result("b", status="unavailable"),
        ]
    )
    assert outcome.verdict == "ensemble_supported"
    assert outcome.disagreement_taxonomy == "single_judge"


def test_single_usable_judge_refuted() -> None:
    outcome = decide_ensemble(
        [
            _result("a", decision="refuted", score=0.1),
            _result("b", status="unavailable"),
        ]
    )
    assert outcome.verdict == "ensemble_refuted"
    assert outcome.disagreement_taxonomy == "single_judge"


def test_all_unavailable() -> None:
    outcome = decide_ensemble(
        [
            _result("a", status="unavailable"),
            _result("b", status="model_error"),
        ]
    )
    assert outcome.verdict == "ensemble_insufficient"
    assert outcome.disagreement_taxonomy == "all_unavailable"


def test_empty_results_is_ensemble_insufficient() -> None:
    outcome = decide_ensemble([])
    assert outcome.verdict == "ensemble_insufficient"
    assert outcome.disagreement_taxonomy == "all_unavailable"
    assert outcome.score_delta is None


def test_timeout_plus_success_yields_single_judge() -> None:
    outcome = decide_ensemble(
        [
            _result("a", status="timeout"),
            _result("b", decision="supported", score=0.8),
        ]
    )
    assert outcome.verdict == "ensemble_supported"
    assert outcome.disagreement_taxonomy == "single_judge"


def test_per_judge_evidence_is_preserved_untouched() -> None:
    results = [
        _result("a", decision="supported", score=0.9),
        _result("b", decision="refuted", score=0.1),
    ]
    outcome = decide_ensemble(results)

    assert outcome.per_judge_results == results
    assert outcome.per_judge_results is results


def test_score_delta_is_analysis_only_not_the_verdict_basis() -> None:
    """Scores are close (small delta) but decisions disagree -- the verdict
    must follow the categorical disagreement, not the numeric spread."""
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.71),
            _result("b", decision="refuted", score=0.69),
        ]
    )
    assert outcome.score_delta is not None
    assert outcome.score_delta < 0.05
    assert outcome.verdict == "ensemble_mixed"
    assert outcome.disagreement_taxonomy == "mixed_support_refute"


def test_score_delta_none_when_fewer_than_two_judges_scored() -> None:
    outcome = decide_ensemble([_result("a", decision="supported", score=0.9)])
    assert outcome.score_delta is None


def test_score_delta_computed_from_scored_judges_regardless_of_decision() -> None:
    """An abstaining judge still produced a score -- score_delta should
    reflect every judge that scored, not just the usable ones."""
    outcome = decide_ensemble(
        [
            _result("a", decision="supported", score=0.9),
            _result("b", decision="abstain", score=0.5),
        ]
    )
    assert outcome.score_delta is not None
    assert abs(outcome.score_delta - 0.4) < 1e-9
