"""
Fill genuine gaps in the demo's RAG coverage, one question at a time.

A real RAG request loads the embedding model, pgvector, Ollama and the rails, and it makes
Gemini calls in the gateway and again in the flash and frontier judges. A previous bulk run
crashed this machine, so this driver is sequential only and has two preventive stops that run
BEFORE each request, not after:

  memory  free memory below MIN_FREE_PERCENT stops the run (the same 25% as demo_seed.py)
  budget  spent so far plus the worst case of one more request must fit under the cap

The worst case of one request is the sum of three ceilings: the gateway's per-call Gemini
ceiling, the largest flash verdict cost ever stored, and the per-call ceiling again for the
frontier judge. Spend is accounted from what the pipeline recorded. The flash verdict cost is
recorded. The gateway's own call is recorded as the change in its run total. The frontier
judge records no cost, so a frontier verdict is charged at its ceiling and the ledger says so.
A question with a complete stored execution is never asked again, and a blocked or error
only question is skipped until nothing else is left, because asking it again usually repeats
the block.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg

from finsentry.archive.coverage import Row, Stored, is_complete, load_stored
from finsentry.risingwave.dao import risingwave_dsn

GATEWAY = "http://localhost:8000"
MIN_FREE_PERCENT = 25
PER_CALL_CEILING = 0.02  # the gateway's own per-call Gemini ceiling (cost_governance)
TARGET_PER_COMPANY = 5
VERDICT_WAIT_S = 150
# A block by a rail is real pipeline output and costs nothing, so a few in a row are expected.
MAX_CONSECUTIVE_INCOMPLETE = 8


@dataclass(frozen=True)
class Slot:
    ticker: str
    query: str
    label: str


def free_memory_percent() -> int:
    out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True).stdout
    return int(out.split("free percentage:")[1].split("%")[0])


def can_afford(spent: float, worst_case: float, cap: float) -> bool:
    """True when the worst case of one more request still fits under the cap."""
    return spent + worst_case <= cap


def plan(
    rows: list[Row],
    target: int = TARGET_PER_COMPANY,
    exclude: frozenset[str] = frozenset(),
    unasked_only: bool = False,
) -> list[Slot]:
    """The slots to fill, in the order to ask them. The homepage question comes first. Then
    the companies furthest from the target take turns, each asking an unstored question
    before a stored-but-incomplete one, and never a blocked or error only one. `exclude` drops
    companies entirely, and `unasked_only` keeps only questions with no stored execution."""
    have: dict[str, int] = {}
    pools: dict[str, list[tuple[int, Slot]]] = {}
    homepage: Slot | None = None
    for r in rows:
        c = r.candidate
        if c.ticker in exclude:
            continue
        have[c.ticker] = have.get(c.ticker, 0) + (1 if r.complete else 0)
        if r.complete:
            continue
        slot = Slot(c.ticker, c.query, c.label)
        if c.homepage:
            homepage = slot
            continue
        kinds = {s.status for s in r.stored}
        if kinds and kinds <= {"blocked", "error"}:
            rank = 2
        else:
            rank = 1 if kinds else 0
        pools.setdefault(c.ticker, []).append((rank, slot))
    out: list[Slot] = []
    if homepage is not None:
        out.append(homepage)
        have[homepage.ticker] = have.get(homepage.ticker, 0) + 1
    for pool in pools.values():
        pool.sort(key=lambda p: p[0])
        pool[:] = [p for p in pool if p[0] == 0 or (p[0] == 1 and not unasked_only)]
    while True:
        need = [t for t in pools if pools[t] and have.get(t, 0) < target]
        if not need:
            return out
        ticker = min(need, key=lambda t: have.get(t, 0))
        out.append(pools[ticker].pop(0)[1])
        have[ticker] = have.get(ticker, 0) + 1


def unrecorded_gateway_charge(
    status: int, body: dict[str, Any], stored_status: str | None
) -> float:
    """What to charge for the gateway's own Gemini call when the response carries no recorded
    cost, because missing usage is not zero. An input rail block (403) uses local models and
    makes no call. A 422 is an output rail block, and only the faithfulness rail calls Gemini.
    A 200 with no cost is free only when the stored event is a retrieval block, which never
    reaches the output rails. Anything else, an error or a timeout included, is charged the
    per-call ceiling."""
    if status == 403:
        return 0.0
    if status == 422:
        return PER_CALL_CEILING if body.get("rail") == "faithfulness" else 0.0
    if status == 200:
        if stored_status == "blocked":
            return 0.0
        return PER_CALL_CEILING
    return PER_CALL_CEILING


def _scalar(sql: str, params: tuple[Any, ...] = ()) -> Any:
    with psycopg.connect(risingwave_dsn()) as conn:
        row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def max_flash_cost() -> float:
    return float(_scalar("SELECT coalesce(max(total_cost_usd), 0) FROM judge_verdicts") or 0.0)


def _wait_for_verdicts(trace_id: str, want_frontier: bool) -> Stored | None:
    deadline = time.monotonic() + VERDICT_WAIT_S
    while time.monotonic() < deadline:
        found = [s for ss in load_stored().values() for s in ss if s.trace_id == trace_id]
        if found and found[0].status != "success":
            return found[
                0
            ]  # a blocked or error event is never judged, so there is nothing to wait for
        if found and found[0].flash_status and (found[0].frontier_count or not want_frontier):
            return found[0]
        time.sleep(3)
    return None


def _latest_rail_cost() -> tuple[int, float]:
    """The gateway's run total as the newest answered event recorded it, so the first request
    of this run is charged only its own change and not everything the process spent before."""
    with psycopg.connect(risingwave_dsn()) as conn:
        row = conn.execute(
            "SELECT (output_rail_trace_snapshot->'faithfulness'->'cost'->>'call_count')::int,"
            " (output_rail_trace_snapshot->'faithfulness'->'cost'->>'run_total_usd')::float8"
            " FROM rag_events WHERE status = 'success'"
            " AND output_rail_trace_snapshot->'faithfulness'->'cost' IS NOT NULL"
            " ORDER BY timestamp_utc DESC LIMIT 1"
        ).fetchone()
    return (int(row[0]), float(row[1])) if row else (0, 0.0)


def run(slots: list[Slot], cap: float, limit: int, spent: float = 0.0) -> None:
    worst = PER_CALL_CEILING + max_flash_cost() + PER_CALL_CEILING
    print(f"worst case per request ${worst:.4f}; cap ${cap:.2f}; spent so far ${spent:.4f};")
    print(f"{len(slots)} slots planned")
    prev_calls, prev_total = _latest_rail_cost()
    failures = 0
    with httpx.Client(timeout=200.0) as client:
        for slot in slots[:limit]:
            free = free_memory_percent()
            if free < MIN_FREE_PERCENT:
                print(f"STOP before {slot.label}: {free}% memory free, below {MIN_FREE_PERCENT}%")
                return
            if not can_afford(spent, worst, cap):
                print(f"STOP before {slot.label}: spent ${spent:.4f} + worst ${worst:.4f} > ${cap}")
                return
            started = time.monotonic()
            resp = client.post(
                f"{GATEWAY}/v1/rag/query", json={"query": slot.query, "ticker": slot.ticker}
            )
            try:
                body: dict[str, Any] = resp.json()
            except ValueError:
                body = {}
            trace = str(body.get("retrieval_trace_id") or body.get("app_trace_id") or "")
            cost = body.get("output_rail_trace", {}).get("faithfulness", {}).get("cost", {})
            calls, total = int(cost.get("call_count", 0)), float(cost.get("run_total_usd", 0.0))
            recorded = bool(cost)
            delta = max(total - prev_total, 0.0) if calls >= prev_calls else total
            if recorded:
                prev_calls, prev_total = calls, total
            # A refused request returns no trace id, so there is nothing to wait for.
            stored = _wait_for_verdicts(trace, _expects_frontier(trace)) if trace else None
            stored_status = stored.status if stored is not None else None
            rail = (
                delta
                if recorded
                else unrecorded_gateway_charge(resp.status_code, body, stored_status)
            )
            flash = float(
                _scalar(
                    "SELECT coalesce(sum(total_cost_usd), 0) FROM judge_verdicts"
                    " WHERE app_trace_id = %s",
                    (trace,),
                )
                or 0.0
            )
            # A delivered answer with no verdict in the wait window may still have been judged.
            if trace and resp.status_code == 200 and stored is None and flash == 0.0:
                flash = max_flash_cost()
            frontier = PER_CALL_CEILING if stored is not None and stored.frontier_count else 0.0
            spent += rail + flash + frontier
            done = stored is not None and is_complete(stored)[0]
            print(
                f"{slot.label}: http {resp.status_code} trace {trace[:8]} "
                f"{stored_status or 'unstored'} {body.get('reason') or body.get('rail') or ''} "
                f"{'complete' if done else 'INCOMPLETE'} rail ${rail:.4f} flash ${flash:.4f} "
                f"frontier(ceiling) ${frontier:.4f} cumulative ${spent:.4f} "
                f"{time.monotonic() - started:.0f}s memory {free}% -> {free_memory_percent()}%"
            )
            failures = 0 if done else failures + 1
            if failures >= MAX_CONSECUTIVE_INCOMPLETE:
                print(f"STOP: {failures} requests in a row did not complete")
                return


def _expects_frontier(trace_id: str) -> bool:
    from finsentry.frontier.sampling import should_sample_for_frontier

    return should_sample_for_frontier(trace_id)


def main(
    cap: float,
    limit: int,
    dry_run: bool,
    spent: float = 0.0,
    exclude: frozenset[str] = frozenset(),
    unasked_only: bool = False,
) -> None:
    from finsentry.archive import coverage

    rows = coverage.matrix(load_stored(), None)
    slots = plan(rows, exclude=exclude, unasked_only=unasked_only)
    if dry_run:
        for s in slots:
            print(f"{s.ticker}\t{s.label}\t{s.query}")
        print(f"{len(slots)} slots")
        return
    run(slots, cap, limit, spent)
