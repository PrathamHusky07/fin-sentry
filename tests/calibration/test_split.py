from __future__ import annotations

from finsentry.calibration.split import (
    SplitAssignment,
    stratified_split,
    stratified_subsample,
)


def _synthetic_ids_by_label(n_positive: int, n_negative: int) -> dict[bool, list[str]]:
    return {
        True: [f"pos-{i}" for i in range(n_positive)],
        False: [f"neg-{i}" for i in range(n_negative)],
    }


def test_split_partitions_every_id_exactly_once() -> None:
    ids_by_label = _synthetic_ids_by_label(50, 200)
    result = stratified_split(ids_by_label, seed="test-seed")

    all_ids = set(ids_by_label[True]) | set(ids_by_label[False])
    assert result.calibration_ids | result.holdout_ids == all_ids
    assert result.calibration_ids & result.holdout_ids == set()


def test_split_preserves_positive_rate_in_each_portion() -> None:
    ids_by_label = _synthetic_ids_by_label(100, 600)
    result = stratified_split(ids_by_label, seed="test-seed", calibration_fraction=0.7)

    cal_positive = len(result.calibration_ids & set(ids_by_label[True]))
    cal_total = len(result.calibration_ids)
    holdout_positive = len(result.holdout_ids & set(ids_by_label[True]))
    holdout_total = len(result.holdout_ids)

    source_rate = 100 / 700
    cal_rate = cal_positive / cal_total
    holdout_rate = holdout_positive / holdout_total

    assert abs(cal_rate - source_rate) < 0.01
    assert abs(holdout_rate - source_rate) < 0.01


def test_split_is_deterministic_across_calls() -> None:
    ids_by_label = _synthetic_ids_by_label(30, 120)
    first = stratified_split(ids_by_label, seed="fixed-seed")
    second = stratified_split(ids_by_label, seed="fixed-seed")

    assert first.calibration_ids == second.calibration_ids
    assert first.holdout_ids == second.holdout_ids


def test_split_changes_with_a_different_seed() -> None:
    ids_by_label = _synthetic_ids_by_label(30, 120)
    a = stratified_split(ids_by_label, seed="seed-a")
    b = stratified_split(ids_by_label, seed="seed-b")

    assert a.calibration_ids != b.calibration_ids


def test_split_respects_calibration_fraction() -> None:
    ids_by_label = _synthetic_ids_by_label(0, 1000)
    result = stratified_split(ids_by_label, seed="test-seed", calibration_fraction=0.7)

    assert abs(len(result.calibration_ids) - 700) <= 1
    assert abs(len(result.holdout_ids) - 300) <= 1


def test_subsample_respects_cap() -> None:
    ids_by_label = _synthetic_ids_by_label(50, 500)
    sample = stratified_subsample(ids_by_label, cap=100, positive_rate=0.1442, seed="s")
    assert len(sample) == 100


def test_subsample_approximates_requested_positive_rate() -> None:
    ids_by_label = _synthetic_ids_by_label(50, 500)
    sample = stratified_subsample(ids_by_label, cap=100, positive_rate=0.1442, seed="s")
    positive_set = set(ids_by_label[True])
    n_positive_in_sample = sum(1 for i in sample if i in positive_set)
    # round(100 * 0.1442) == 14
    assert n_positive_in_sample == 14


def test_subsample_is_deterministic() -> None:
    ids_by_label = _synthetic_ids_by_label(50, 500)
    first = stratified_subsample(ids_by_label, cap=100, positive_rate=0.1442, seed="s")
    second = stratified_subsample(ids_by_label, cap=100, positive_rate=0.1442, seed="s")
    assert first == second


def test_subsample_never_exceeds_available_ids() -> None:
    ids_by_label = _synthetic_ids_by_label(5, 10)
    sample = stratified_subsample(ids_by_label, cap=1000, positive_rate=0.1442, seed="s")
    assert len(sample) == 15


def test_subsample_backfills_when_one_class_runs_out() -> None:
    """Requesting more positives than exist must not silently return fewer
    than `cap` ids when the negative pool has room to cover the gap."""
    ids_by_label = _synthetic_ids_by_label(2, 200)
    sample = stratified_subsample(ids_by_label, cap=50, positive_rate=0.5, seed="s")
    assert len(sample) == 50


def test_split_assignment_is_a_plain_dataclass() -> None:
    assignment = SplitAssignment(calibration_ids={"a"}, holdout_ids={"b"})
    assert assignment.calibration_ids == {"a"}
    assert assignment.holdout_ids == {"b"}
