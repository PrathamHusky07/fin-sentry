from __future__ import annotations

import math

from finsentry.calibration.metrics import (
    accuracy,
    average_precision,
    cohens_kappa,
    confusion_matrix,
    pr_auc,
    precision_recall_f1,
    roc_auc,
    select_recall_favoring_threshold,
    specificity_fpr_fnr,
    sweep_thresholds,
    wilson_interval,
)


def test_confusion_matrix_counts_all_four_cells() -> None:
    gold = [True, True, False, False]
    predicted = [True, False, True, False]
    cm = confusion_matrix(gold, predicted)
    assert (cm.tp, cm.fp, cm.tn, cm.fn) == (1, 1, 1, 1)
    assert cm.n == 4


def test_confusion_matrix_perfect_predictions() -> None:
    gold = [True, True, False, False, False]
    predicted = [True, True, False, False, False]
    cm = confusion_matrix(gold, predicted)
    assert (cm.tp, cm.fp, cm.tn, cm.fn) == (2, 0, 3, 0)


def test_precision_recall_f1_known_values() -> None:
    gold = [True, True, True, False, False]
    predicted = [True, True, False, True, False]
    cm = confusion_matrix(gold, predicted)
    precision, recall, f1 = precision_recall_f1(cm)
    assert precision == 2 / 3
    assert recall == 2 / 3
    assert math.isclose(f1, 2 / 3)


def test_precision_recall_f1_zero_predicted_positive_is_zero_not_nan() -> None:
    gold = [True, False]
    predicted = [False, False]
    cm = confusion_matrix(gold, predicted)
    precision, recall, f1 = precision_recall_f1(cm)
    assert precision == 0.0
    assert recall == 0.0
    assert f1 == 0.0


def test_specificity_fpr_fnr_known_values() -> None:
    gold = [True, True, False, False]
    predicted = [True, False, False, True]
    cm = confusion_matrix(gold, predicted)
    specificity, fpr, fnr = specificity_fpr_fnr(cm)
    assert specificity == 0.5
    assert fpr == 0.5
    assert fnr == 0.5


def test_accuracy_known_value() -> None:
    gold = [True, True, False, False]
    predicted = [True, True, False, True]
    cm = confusion_matrix(gold, predicted)
    assert accuracy(cm) == 0.75


def test_cohens_kappa_perfect_agreement_is_one() -> None:
    gold = [True, True, False, False, False, True]
    predicted = [True, True, False, False, False, True]
    cm = confusion_matrix(gold, predicted)
    assert math.isclose(cohens_kappa(cm), 1.0)


def test_cohens_kappa_is_zero_for_chance_level_agreement() -> None:
    # Predicted positive rate 50%, gold positive rate 50%, and the
    # predictions are independent of gold (every combination appears
    # equally) -- expected agreement equals chance agreement, kappa ~ 0.
    gold = [True, True, False, False]
    predicted = [True, False, True, False]
    cm = confusion_matrix(gold, predicted)
    assert math.isclose(cohens_kappa(cm), 0.0, abs_tol=1e-9)


def test_cohens_kappa_below_chance_is_negative() -> None:
    gold = [True, True, False, False]
    predicted = [False, False, True, True]  # systematically backwards
    cm = confusion_matrix(gold, predicted)
    assert cohens_kappa(cm) < 0


def test_roc_auc_perfect_separation_is_one() -> None:
    gold = [True, True, False, False]
    scores = [0.9, 0.8, 0.2, 0.1]
    auc = roc_auc(gold, scores)
    assert auc == 1.0


def test_roc_auc_perfect_inversion_is_zero() -> None:
    gold = [True, True, False, False]
    scores = [0.1, 0.2, 0.8, 0.9]
    auc = roc_auc(gold, scores)
    assert auc == 0.0


def test_roc_auc_random_scores_is_near_half() -> None:
    gold = [True, False, True, False]
    scores = [0.5, 0.5, 0.5, 0.5]
    auc = roc_auc(gold, scores)
    assert auc == 0.5


def test_roc_auc_none_when_one_class_absent() -> None:
    assert roc_auc([True, True], [0.9, 0.8]) is None
    assert roc_auc([False, False], [0.9, 0.8]) is None


def test_pr_auc_perfect_separation_is_one() -> None:
    gold = [True, True, False, False]
    scores = [0.9, 0.8, 0.2, 0.1]
    assert math.isclose(pr_auc(gold, scores), 1.0)


def test_pr_auc_none_when_no_positives() -> None:
    assert pr_auc([False, False], [0.9, 0.1]) is None


def test_pr_auc_worse_than_perfect_scores_lower() -> None:
    gold = [True, True, False, False]
    perfect = [0.9, 0.8, 0.2, 0.1]
    worse = [0.9, 0.1, 0.8, 0.2]  # one positive and one negative swapped in rank
    assert pr_auc(gold, worse) < pr_auc(gold, perfect)


def test_sweep_thresholds_covers_every_requested_threshold() -> None:
    gold = [True, False, True, False]
    scores = [0.9, 0.1, 0.6, 0.4]
    thresholds = [0.0, 0.5, 1.0]
    points = sweep_thresholds(gold, scores, thresholds)
    assert [p.threshold for p in points] == thresholds


def test_sweep_thresholds_low_threshold_predicts_everything_positive() -> None:
    gold = [True, False, True, False]
    scores = [0.9, 0.1, 0.6, 0.4]
    points = sweep_thresholds(gold, scores, [0.0])
    assert points[0].confusion.fn == 0
    assert points[0].recall == 1.0


def test_sweep_thresholds_high_threshold_predicts_everything_negative() -> None:
    gold = [True, False, True, False]
    scores = [0.9, 0.1, 0.6, 0.4]
    points = sweep_thresholds(gold, scores, [1.01])
    assert points[0].confusion.tp == 0
    assert points[0].confusion.fp == 0


def test_select_recall_favoring_threshold_picks_highest_recall_above_floor() -> None:
    gold = [True, True, True, False, False, False, False, False, False, False]
    scores = [0.9, 0.6, 0.3, 0.8, 0.5, 0.4, 0.2, 0.1, 0.05, 0.02]
    points = sweep_thresholds(gold, scores, [0.0, 0.2, 0.35, 0.55, 0.65, 0.85, 1.0])
    chosen = select_recall_favoring_threshold(points, min_precision=0.3)
    # Both threshold=0.0 and threshold=0.2 reach recall=1.0 (all 3 positives
    # score >=0.2); among recall-1.0 ties the higher-F1 point wins, and
    # either way the floor must hold.
    assert chosen.recall == 1.0
    assert chosen.precision >= 0.3


def test_select_recall_favoring_threshold_falls_back_when_nothing_clears_floor() -> None:
    # 2 positives (0.9, 0.6), 8 negatives (0.7 and seven at 0.1).
    gold = [True, True, False, False, False, False, False, False, False, False]
    scores = [0.9, 0.6, 0.7, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    points = sweep_thresholds(gold, scores, [0.0, 0.65])
    # threshold=0.0: predicts everyone positive -> tp=2, fp=8,
    #   precision=0.2, recall=1.0, f1=2*0.2*1/1.2=1/3.
    # threshold=0.65: predicts {0.9, 0.7} positive -> tp=1, fp=1,
    #   precision=0.5, recall=0.5, f1=0.5.
    # min_precision=0.6 clears neither point (0.2 and 0.5 both < 0.6), so
    # this genuinely exercises the no-eligible-point fallback -- unlike a
    # floor that some point still clears. The fallback must pick by
    # highest F1 (threshold=0.65, f1=0.5), NOT by highest recall
    # (threshold=0.0, recall=1.0, which has the lower f1=1/3): a
    # recall-first fallback would pick the wrong point here.
    chosen = select_recall_favoring_threshold(points, min_precision=0.6)
    assert chosen.threshold == 0.65
    assert chosen.f1 == 0.5
    assert chosen.recall == 0.5
    assert chosen.precision == 0.5


def test_average_precision_perfect_separation_is_one() -> None:
    gold = [True, True, False, False]
    scores = [0.9, 0.8, 0.2, 0.1]
    assert math.isclose(average_precision(gold, scores), 1.0)


def test_average_precision_none_when_no_positives() -> None:
    assert average_precision([False, False], [0.9, 0.1]) is None


def test_average_precision_tied_scores_computed_by_hand() -> None:
    # gold=[True, True, False], scores=[1.0, 0.5, 0.5]. 2 positives total.
    # Distinct score 1.0: one row (True) -> tp=1, fp=0.
    #   recall=1/2=0.5, precision=1/1=1.0.
    #   contribution = 1.0 * (0.5 - 0.0) = 0.5
    # Distinct score 0.5 (tied group, both rows folded in together):
    #   -> tp=2, fp=1. recall=2/2=1.0, precision=2/3.
    #   contribution = (2/3) * (1.0 - 0.5) = 1/3
    # AP = 0.5 + 1/3 = 5/6
    gold = [True, True, False]
    scores = [1.0, 0.5, 0.5]
    assert math.isclose(average_precision(gold, scores), 5 / 6)


def test_average_precision_is_not_optimistic_about_ties_like_trapezoidal_pr_auc() -> None:
    # Same tied case as above: trapezoidal pr_auc draws a straight line
    # between the (recall=0.5, precision=1.0) point and the
    # (recall=1.0, precision=2/3) point, crediting an average precision
    # of (1.0 + 2/3)/2 = 5/6 over that segment -- which happens to equal
    # AP here by coincidence of this particular example having only two
    # distinct thresholds. Use a second tied group to show the general
    # case: AP must never exceed pr_auc on the same (gold, scores), since
    # trapezoidal interpolation across ties can only be optimistic or
    # equal, never pessimistic.
    gold = [True, True, True, False, False, False]
    scores = [1.0, 0.5, 0.5, 0.5, 0.5, 0.0]
    ap = average_precision(gold, scores)
    trap = pr_auc(gold, scores)
    assert ap is not None and trap is not None
    assert ap <= trap + 1e-12


def test_wilson_interval_hand_computed_successes_equal_n() -> None:
    # successes=1, n=1, z=1.96 (z^2=3.8416, chosen for clean arithmetic).
    # phat=1.0, denom=1+3.8416/1=4.8416, center=1+3.8416/2=2.9208,
    # margin=1.96*sqrt(1*0/1 + 3.8416/4)=1.96*sqrt(0.9604)=1.96*0.98=1.9208
    # low=(2.9208-1.9208)/4.8416=1.0/4.8416=0.206542...
    # high=(2.9208+1.9208)/4.8416=4.8416/4.8416=1.0
    low, high = wilson_interval(successes=1, n=1, z=1.96)
    assert math.isclose(low, 1.0 / 4.8416, rel_tol=1e-9)
    assert math.isclose(high, 1.0, rel_tol=1e-9)


def test_wilson_interval_degenerate_n_zero_does_not_divide_by_zero() -> None:
    assert wilson_interval(successes=0, n=0) == (0.0, 1.0)
