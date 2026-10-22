"""
The RAG coverage matrix: for each question the demo should have an answer to, what is
actually stored, read from RisingWave (the query layer) and the archive.

A question is covered only by a COMPLETE execution: status success with an answer and
retrieved chunks, a flash verdict that scored all three metrics, and a frontier verdict
when the normal one-in-ten hash rule would have sampled the trace. A blocked or error
execution is stored but is not an answered example, and a trace with no verdict is not
complete. The sampling rule is the real one (frontier.sampling), but the consumer lowers
the rate under backlog, so "expected" is the rule's prediction, not a guarantee.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from finsentry.archive.export import ROOT
from finsentry.frontier.sampling import should_sample_for_frontier
from finsentry.risingwave.dao import risingwave_dsn

SEED_DIR = ROOT / "docs" / "demo-seed"


@dataclass(frozen=True)
class Candidate:
    ticker: str
    query: str
    label: str
    homepage: bool = False


@dataclass(frozen=True)
class Stored:
    event_id: str
    trace_id: str
    status: str
    has_answer: bool
    has_chunks: bool
    flash_status: str | None
    frontier_count: int


@dataclass(frozen=True)
class Row:
    candidate: Candidate
    stored: list[Stored]
    complete: Stored | None
    frontier_expected: bool | None
    in_archive: bool | None


def candidates() -> list[Candidate]:
    """The committed question set, plus the exact homepage question read from the historical
    capture. Nothing is typed in here: both come from files in docs/demo-seed."""
    seed = json.loads((SEED_DIR / "demo-questions-v1.json").read_text())
    out = [Candidate(q["ticker"], q["query"], q["id"]) for q in seed["questions"]]
    capture = json.loads((SEED_DIR / "amzn-disagreement-v1.json").read_text())
    out.append(Candidate(capture["ticker"], capture["query"], "AMZN-homepage", homepage=True))
    return out


def is_complete(s: Stored) -> tuple[bool, bool]:
    """(complete, frontier_expected) for one stored execution."""
    expected = should_sample_for_frontier(s.trace_id)
    answered = s.status == "success" and s.has_answer and s.has_chunks
    flashed = s.flash_status == "complete"
    return answered and flashed and (s.frontier_count > 0 or not expected), expected


def load_stored() -> dict[tuple[str, str], list[Stored]]:
    sql = (
        "SELECT e.ticker, e.query, e.event_id, e.app_trace_id, e.status,"
        " coalesce(length(e.answer), 0) > 0,"
        " coalesce(jsonb_array_length(e.retrieved_chunk_ids), 0) > 0,"
        " (SELECT v.status FROM judge_verdicts v WHERE v.app_trace_id = e.app_trace_id"
        "  ORDER BY v.timestamp_utc DESC LIMIT 1),"
        " (SELECT count(*) FROM rag_frontier_verdicts f WHERE f.app_trace_id = e.app_trace_id)"
        " FROM rag_events e WHERE e.ticker IS NOT NULL ORDER BY e.timestamp_utc"
    )
    out: dict[tuple[str, str], list[Stored]] = {}
    with psycopg.connect(risingwave_dsn()) as conn:
        for t, q, ev, tr, st, ans, chunks, fl, fr in conn.execute(sql).fetchall():
            out.setdefault((str(t), str(q)), []).append(
                Stored(str(ev), str(tr), str(st), bool(ans), bool(chunks), fl, int(fr))
            )
    return out


def archived_event_ids(directory: Path) -> set[str]:
    path = directory / "stream" / "rag-responses.jsonl"
    if not path.is_file():
        return set()
    return {
        json.loads(ln)["value"]["event_id"] for ln in path.read_text("utf-8").splitlines() if ln
    }


def matrix(stored: dict[tuple[str, str], list[Stored]], archive_ids: set[str] | None) -> list[Row]:
    rows: list[Row] = []
    for c in candidates():
        found = stored.get((c.ticker, c.query), [])
        complete: Stored | None = None
        expected: bool | None = None
        for s in found:
            ok, exp = is_complete(s)
            if ok:
                complete, expected = s, exp
                break
        in_archive = (
            None if complete is None or archive_ids is None else (complete.event_id in archive_ids)
        )
        rows.append(Row(c, found, complete, expected, in_archive))
    return rows


def render(rows: list[Row]) -> str:
    lines = [
        "| company | question | stored | complete | frontier expected | in archive | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        kinds = ",".join(sorted({s.status for s in r.stored})) or "none"
        note = "exact homepage question" if r.candidate.homepage else ""
        lines.append(
            f"| {r.candidate.ticker} | {r.candidate.label} | {kinds} |"
            f" {'yes' if r.complete else 'no'} |"
            f" {'-' if r.frontier_expected is None else ('yes' if r.frontier_expected else 'no')} |"
            f" {'-' if r.in_archive is None else ('yes' if r.in_archive else 'no')} | {note} |"
        )
    return "\n".join(lines)


def per_company(rows: list[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.candidate.ticker] = out.get(r.candidate.ticker, 0) + (1 if r.complete else 0)
    return out
