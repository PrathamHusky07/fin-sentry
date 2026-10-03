from __future__ import annotations

import math

from finsentry.calibration.metrics import (
    accuracy,
    cohens_kappa,
    confusion_matrix,
    pr_auc,
    precision_recall_f1,
    roc_auc,
    select_recall_favoring_threshold,
    specificity_fpr_fnr,
    sweep_thresholds,
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
    gold = [True, False, False, False, False]
    scores = [0.6, 0.5, 0.4, 0.3, 0.2]
    points = sweep_thresholds(gold, scores, [0.0, 0.55, 1.0])
    chosen = select_recall_favoring_threshold(points, min_precision=0.99)
    # Nothing reaches 0.99 precision; must still return some point rather
    # than raising, falling back to best F1.
    assert chosen is not None
