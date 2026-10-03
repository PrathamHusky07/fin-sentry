"""
Deterministic, stratified calibration/held-out split for benchmark rows.

Hash-based on (id, seed) rather than random.shuffle: the same seed always
produces the same split, so a resumed or re-run calibration session never
reshuffles which rows are calibration-only vs held-out-only. Stratified
per class (not a single pooled hash-threshold) so both splits keep the
source dataset's positive rate exactly, not just approximately.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

DEFAULT_SEED = "d5a-m4-finqa-split-v1"
DEFAULT_CALIBRATION_FRACTION = 0.7


@dataclass
class SplitAssignment:
    calibration_ids: set[str]
    holdout_ids: set[str]


def _hash_rank(row_id: str, seed: str) -> float:
    """A value in [0, 1), deterministic given (row_id, seed)."""
    digest = hashlib.sha256(f"{seed}:{row_id}".encode()).hexdigest()
    return float(int(digest, 16)) / float(16 ** len(digest))


def stratified_split(
    ids_by_label: dict[bool, list[str]],
    seed: str = DEFAULT_SEED,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> SplitAssignment:
    """Split each label group independently so both splits preserve the
    source positive rate exactly, not approximately.

    ids_by_label: {True: [...hallucination ids...], False: [...faithful ids...]}
    """
    calibration_ids: set[str] = set()
    holdout_ids: set[str] = set()
    for _label, ids in ids_by_label.items():
        ordered = sorted(ids, key=lambda row_id: _hash_rank(row_id, seed))
        split_point = round(len(ordered) * calibration_fraction)
        calibration_ids.update(ordered[:split_point])
        holdout_ids.update(ordered[split_point:])
    return SplitAssignment(calibration_ids=calibration_ids, holdout_ids=holdout_ids)


def stratified_subsample(
    ids_by_label: dict[bool, list[str]],
    cap: int,
    positive_rate: float,
    seed: str,
) -> list[str]:
    """Deterministically pick up to `cap` ids from ids_by_label, holding
    the sample's positive rate close to `positive_rate` (rounded to whole
    rows), so a Gemini-call budget spent on a subset still reflects the
    benchmark's real class balance rather than an arbitrary slice of it.
    """
    positive_ids = sorted(
        ids_by_label.get(True, []), key=lambda row_id: _hash_rank(row_id, f"{seed}:subsample")
    )
    negative_ids = sorted(
        ids_by_label.get(False, []), key=lambda row_id: _hash_rank(row_id, f"{seed}:subsample")
    )

    n_positive = min(len(positive_ids), round(cap * positive_rate))
    n_negative = min(len(negative_ids), cap - n_positive)
    # If negatives ran out first, backfill from positives (and vice versa)
    # rather than silently returning fewer than `cap` ids when more are available.
    n_positive = min(len(positive_ids), cap - n_negative)

    return positive_ids[:n_positive] + negative_ids[:n_negative]
