"""The coverage matrix classifies stored executions without a database: what counts as
complete, how the sampling rule changes what is expected, and where the question text
comes from."""

from __future__ import annotations

import json
import uuid

from finsentry.archive.coverage import (
    SEED_DIR,
    Stored,
    candidates,
    is_complete,
    matrix,
    per_company,
)
from finsentry.frontier.sampling import should_sample_for_frontier


def _trace(sampled: bool) -> str:
    while True:
        t = str(uuid.uuid4())
        if should_sample_for_frontier(t) == sampled:
            return t


def _stored(trace: str, **over: object) -> Stored:
    base: dict[str, object] = {
        "event_id": "ev-" + trace[:6],
        "trace_id": trace,
        "status": "success",
        "has_answer": True,
        "has_chunks": True,
        "flash_status": "complete",
        "frontier_count": 0,
    }
    base.update(over)
    return Stored(**base)  # type: ignore[arg-type]


def test_the_candidates_are_the_committed_questions_plus_the_verbatim_homepage_question() -> None:
    found = candidates()
    capture = json.loads((SEED_DIR / "amzn-disagreement-v1.json").read_text())
    homepage = [c for c in found if c.homepage]
    assert len(found) == 41 and len(homepage) == 1
    assert (
        homepage[0].query
        == capture["query"]
        == ("What is Amazon's FY2024 net income attributable to shareholders (in USD millions)?")
    )
    assert len({(c.ticker, c.query) for c in found}) == 41


def test_a_sampled_trace_is_complete_only_with_its_frontier_verdict() -> None:
    sampled = _trace(True)
    assert is_complete(_stored(sampled)) == (False, True)
    assert is_complete(_stored(sampled, frontier_count=1)) == (True, True)


def test_an_unsampled_trace_is_complete_with_a_flash_verdict_alone() -> None:
    assert is_complete(_stored(_trace(False))) == (True, False)


def test_a_trace_missing_its_answer_chunks_or_a_complete_flash_verdict_is_not_complete() -> None:
    t = _trace(False)
    for over in (
        {"status": "blocked"},
        {"status": "error"},
        {"has_answer": False},
        {"has_chunks": False},
        {"flash_status": None},
        {"flash_status": "partial"},
    ):
        assert is_complete(_stored(t, **over))[0] is False, over


def test_the_matrix_counts_complete_questions_per_company_and_ignores_blocked_ones() -> None:
    first = candidates()[0]
    stored = {
        (first.ticker, first.query): [
            _stored(_trace(False), status="blocked"),
            _stored(_trace(False)),
        ]
    }
    rows = matrix(stored, {"nope"})
    by_label = {r.candidate.label: r for r in rows}
    assert by_label[first.label].complete is not None
    assert by_label[first.label].in_archive is False
    assert per_company(rows)[first.ticker] == 1
    assert sum(per_company(rows).values()) == 1
    assert matrix({}, None)[0].in_archive is None
