"""
Deterministic metric functions for judge calibration against a labeled
benchmark. Pure, no I/O, no model calls -- unit-tested with synthetic
inputs (Day 5 M4). Judges are calibrated here; they are never the test
oracle (CLAUDE.md: "Verification is deterministic. Judges are not
verification.").

No scikit-learn dependency: it is only a transitive dependency of this
repo (pulled in by sentence-transformers) and never imported directly
anywhere else in finsentry/, so ROC-AUC and PR-AUC are implemented here
from first principles rather than adding an undeclared direct dependency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


def confusion_matrix(gold: list[bool], predicted: list[bool]) -> ConfusionMatrix:
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must be the same length")
    tp = sum(1 for g, p in zip(gold, predicted, strict=True) if g and p)
    fp = sum(1 for g, p in zip(gold, predicted, strict=True) if not g and p)
    tn = sum(1 for g, p in zip(gold, predicted, strict=True) if not g and not p)
    fn = sum(1 for g, p in zip(gold, predicted, strict=True) if g and not p)
    return ConfusionMatrix(tp=tp, fp=fp, tn=tn, fn=fn)


def precision_recall_f1(cm: ConfusionMatrix) -> tuple[float, float, float]:
    precision = cm.tp / (cm.tp + cm.fp) if (cm.tp + cm.fp) > 0 else 0.0
    recall = cm.tp / (cm.tp + cm.fn) if (cm.tp + cm.fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1


def specificity_fpr_fnr(cm: ConfusionMatrix) -> tuple[float, float, float]:
    specificity = cm.tn / (cm.tn + cm.fp) if (cm.tn + cm.fp) > 0 else 0.0
    fpr = 1.0 - specificity
    recall = cm.tp / (cm.tp + cm.fn) if (cm.tp + cm.fn) > 0 else 0.0
    fnr = 1.0 - recall
    return specificity, fpr, fnr


def accuracy(cm: ConfusionMatrix) -> float:
    return (cm.tp + cm.tn) / cm.n if cm.n > 0 else 0.0


def cohens_kappa(cm: ConfusionMatrix) -> float:
    """Agreement between the judge's thresholded decision and the gold
    label, chance-corrected. Framed as agreement with a reference label,
    NOT inter-annotator agreement -- there is only one rater here (the
    judge) being checked against ground truth, not two human raters.
    """
    n = cm.n
    if n == 0:
        return 0.0
    po = accuracy(cm)
    predicted_positive_rate = (cm.tp + cm.fp) / n
    gold_positive_rate = (cm.tp + cm.fn) / n
    predicted_negative_rate = (cm.tn + cm.fn) / n
    gold_negative_rate = (cm.tn + cm.fp) / n
    pe = (predicted_positive_rate * gold_positive_rate) + (
        predicted_negative_rate * gold_negative_rate
    )
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def roc_auc(gold: list[bool], scores: list[float]) -> float | None:
    """Mann-Whitney U formulation: P(score_positive > score_negative),
    with ties counted as half a win. Returns None when one class is
    entirely absent (ROC-AUC is undefined without both classes).
    """
    positives = [s for g, s in zip(gold, scores, strict=True) if g]
    negatives = [s for g, s in zip(gold, scores, strict=True) if not g]
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def pr_auc(gold: list[bool], scores: list[float]) -> float | None:
    """Area under the precision-recall curve via trapezoidal integration
    over recall, walking distinct score thresholds from high to low.
    Returns None when there are no positives (precision/recall undefined).

    Secondary diagnostic only. `average_precision` above is the headline
    PR metric: it does not interpolate across tied scores, which this
    function does, and tied scores are the common case for this judge
    (see `average_precision`'s docstring). Kept for comparison, not
    reporting authority.
    """
    total_positive = sum(1 for g in gold if g)
    if total_positive == 0:
        return None

    pairs = sorted(zip(scores, gold, strict=True), key=lambda pair: pair[0], reverse=True)

    points: list[tuple[float, float]] = [(0.0, 1.0)]  # (recall, precision) at threshold=+inf
    tp = 0
    fp = 0
    for score, is_positive in pairs:
        if is_positive:
            tp += 1
        else:
            fp += 1
        recall = tp / total_positive
        precision = tp / (tp + fp)
        points.append((recall, precision))

    area = 0.0
    for (r0, p0), (r1, p1) in zip(points, points[1:]):
        area += (r1 - r0) * (p0 + p1) / 2.0
    return area


def average_precision(gold: list[bool], scores: list[float]) -> float | None:
    """Average Precision: the step-function area under the precision-recall
    curve, computed at each distinct score value rather than interpolated
    between them. Returns None when there are no positives (undefined).

    This is the headline PR metric for this judge, not `pr_auc` below.
    `pr_auc` draws a straight line (trapezoid) between consecutive
    (recall, precision) points, which is a fine approximation when scores
    are continuous and finely spaced -- but this judge's rubric only ever
    emits faithfulness in {0.0, 0.5, 1.0}, so detector_score is quantized
    to three values and many rows tie on the same score. Trapezoidal
    interpolation across a tie is optimistic: it credits the detector for
    precision values it never actually produced at any real threshold,
    because it averages the precision just before a block of ties with
    the precision just after it, rather than reporting the precision that
    block of ties actually achieves. AP avoids this by processing every
    row that shares a score as a single step: all of them are folded into
    the confusion counts together before precision is read off, so the
    reported value is always a precision the detector actually attains at
    some real threshold.
    """
    total_positive = sum(1 for g in gold if g)
    if total_positive == 0:
        return None

    pairs = sorted(zip(scores, gold, strict=True), key=lambda pair: pair[0], reverse=True)

    ap = 0.0
    tp = 0
    fp = 0
    prev_recall = 0.0
    i = 0
    n = len(pairs)
    while i < n:
        current_score = pairs[i][0]
        j = i
        while j < n and pairs[j][0] == current_score:
            if pairs[j][1]:
                tp += 1
            else:
                fp += 1
            j += 1
        recall = tp / total_positive
        precision = tp / (tp + fp)
        ap += precision * (recall - prev_recall)
        prev_recall = recall
        i = j
    return ap


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion
    (successes / n), e.g. precision or recall at a fixed threshold.
    Preferred over the normal (Wald) interval here because n is small
    (tens of held-out rows, sometimes single-digit positive counts) and
    Wald intervals are known to misbehave -- including going outside
    [0, 1] -- at small n or proportions near 0 or 1.

    n=0 is degenerate (no trials to bound a proportion from): defined
    here as the maximally uninformative interval (0.0, 1.0) rather than
    dividing by zero, since zero observations rule nothing out.
    """
    if n == 0:
        return (0.0, 1.0)
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = phat + z2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    low = (center - margin) / denom
    high = (center + margin) / denom
    return (max(0.0, low), min(1.0, high))


@dataclass
class ThresholdSweepPoint:
    threshold: float
    confusion: ConfusionMatrix
    precision: float
    recall: float
    f1: float
    specificity: float
    fpr: float
    fnr: float
    kappa: float
    accuracy: float


def sweep_thresholds(
    gold: list[bool], detector_scores: list[float], thresholds: list[float]
) -> list[ThresholdSweepPoint]:
    """Evaluate every threshold independently; predicted positive iff
    detector_score >= threshold."""
    points: list[ThresholdSweepPoint] = []
    for t in thresholds:
        predicted = [s >= t for s in detector_scores]
        cm = confusion_matrix(gold, predicted)
        precision, recall, f1 = precision_recall_f1(cm)
        specificity, fpr, fnr = specificity_fpr_fnr(cm)
        points.append(
            ThresholdSweepPoint(
                threshold=t,
                confusion=cm,
                precision=precision,
                recall=recall,
                f1=f1,
                specificity=specificity,
                fpr=fpr,
                fnr=fnr,
                kappa=cohens_kappa(cm),
                accuracy=accuracy(cm),
            )
        )
    return points


def select_recall_favoring_threshold(
    points: list[ThresholdSweepPoint], min_precision: float = 0.2
) -> ThresholdSweepPoint:
    """Pick an operating point reflecting the asymmetric cost of missing a
    hallucination (a false negative reaches the user; a false positive
    only costs a human review).

    min_precision is a policy floor, not a tuned value: below it the
    detector would flag too many faithful responses to be usable even
    though recall-favoring is the stated objective.

    Selection policy, applied in order:
      1. Restrict to points with precision >= min_precision.
      2. Among those, pick the highest recall. Ties broken by highest F1,
         then by lowest threshold -- so a tie always resolves to the same
         point, not whichever happened to sort first.
      3. If no point clears the floor, fall back to the single best-F1
         point across ALL points (ties broken by lowest threshold)
         instead of raising, so a threshold is always selected. This is a
         different ranking from step 2: it optimizes F1 first because
         there is no eligible precision floor left to anchor a
         recall-first choice to.
    """
    eligible = [p for p in points if p.precision >= min_precision]
    if eligible:
        return min(eligible, key=lambda p: (-p.recall, -p.f1, p.threshold))
    return min(points, key=lambda p: (-p.f1, p.threshold))
