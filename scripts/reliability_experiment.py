#!/usr/bin/env python3
"""Day 9 reliability experiment runner: one phase of one failure scenario.

Sends a small, fixed number of real queries to the running gateway, waits for
the async judge tiers to settle, then reads back what was actually persisted
(RisingWave rows and the gateway's public trace classification). Nothing here
simulates a result. The failure itself is injected outside this script (for
example by restarting a consumer with a broken GEMINI_MODEL) and described in
--injection so the output file says what was done.

Each call appends one phase record to --out, so a scenario file holds its
"injected" phase and its "recovered" phase side by side.

Run with:
    python scripts/reliability_experiment.py --experiment A --phase injected \\
        --questions 0:6 --injection "flash consumer restarted with GEMINI_MODEL=..." \\
        --out docs/measurements/reliability/exp-a-flash-judge-failure.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import psycopg.rows
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.events.schema import RagResponseEvent
from finsentry.events.topics import RAG_RESPONSES_TOPIC
from finsentry.frontier.sampling import should_sample_for_frontier
from finsentry.risingwave.dao import risingwave_dsn

GATEWAY = "http://localhost:8000"

# Real demo questions, each already present in the persisted trace store.
QUESTIONS: list[tuple[str, str]] = [
    ("AAPL", "What was Apple's total net sales for fiscal year 2024?"),
    (
        "MSFT",
        "What was Microsoft's Intelligent Cloud segment revenue in its most recent 10-K filing?",
    ),
    (
        "NVDA",
        "What was NVIDIA's gross margin percentage in its most recent fiscal year 10-K filing?",
    ),
    (
        "AMZN",
        "What was Amazon's total net sales for the quarter covered by its most recent 10-Q filing?",
    ),
    (
        "MSFT",
        "What was Microsoft's revenue for the quarter covered by its most recent 10-Q filing?",
    ),
    (
        "JPM",
        "What was JPMorgan Chase's return on tangible common equity (ROTCE) in its most recent fiscal year?",  # noqa: E501
    ),
    (
        "JPM",
        "What was JPMorgan Chase's net income for the quarter covered by its most recent 10-Q filing?",  # noqa: E501
    ),
    (
        "JPM",
        "How did JPMorgan Chase's provision for credit losses change between its most recent fiscal year and the prior fiscal year?",  # noqa: E501
    ),
    (
        "AMZN",
        "What risk factors does Amazon's most recent 10-K identify related to its fulfillment and logistics network?",  # noqa: E501
    ),
    (
        "JPM",
        "What was JPMorgan Chase's Consumer and Community Banking segment net income in its most recent 10-K filing?",  # noqa: E501
    ),
]


def send(questions: list[tuple[str, str]]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    with httpx.Client(timeout=200.0) as client:
        for ticker, query in questions:
            t0 = time.monotonic()
            started = datetime.now(UTC).isoformat()
            resp = client.post(f"{GATEWAY}/v1/rag/query", json={"query": query, "ticker": ticker})
            body: dict[str, Any] = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            sent.append(
                {
                    "ticker": ticker,
                    "query": query,
                    "sent_at_utc": started,
                    "http_status": resp.status_code,
                    "client_latency_ms": int((time.monotonic() - t0) * 1000),
                    "app_trace_id": body.get("retrieval_trace_id"),
                }
            )
            print(f"  sent {ticker}: http {resp.status_code} in {sent[-1]['client_latency_ms']} ms")
    return sent


def publish_candidates(
    conn: psycopg.Connection[Any], source_trace_id: str, n: int, sampled: bool | None
) -> list[dict[str, Any]]:
    """Publish n copies of one real persisted success event under fresh trace ids.

    The gateway always mints its own trace id, so a request cannot be steered
    into the deterministic ~10% frontier sample. Instead a uuid is drawn until
    the real sampling hash gives the wanted decision (checked here, before
    anything is sent) and the copy goes straight onto the rag-responses topic.
    The query is prefixed so the copy can never pass for organic traffic."""
    src = _rows(conn, "SELECT * FROM rag_events WHERE app_trace_id = %s", (source_trace_id,))[0]
    assert src["status"] == "success", "source trace must be a delivered answer"
    events: list[RagResponseEvent] = []
    while len(events) < n:
        tid = str(uuid.uuid4())
        if sampled is not None and should_sample_for_frontier(tid) is not sampled:
            continue
        events.append(
            RagResponseEvent(
                event_id=str(uuid.uuid4()),
                app_trace_id=tid,
                timestamp_utc=datetime.now(UTC).isoformat(),
                status="success",
                endpoint=src["endpoint"],
                query=f"[experiment candidate, copy of trace {source_trace_id[:8]}] {src['query']}",
                ticker=src["ticker"],
                retrieved_chunk_ids=src["retrieved_chunk_ids"],
                retrieved_chunks_text=src["retrieved_chunks_text"],
                answer=src["answer"],
                citations=src["citations"],
                confidence=src["confidence"],
                model_used=src["model_used"],
                input_rail_status=src["input_rail_status"],
                output_rail_trace_snapshot=src["output_rail_trace_snapshot"] or {},
                total_latency_ms=src["total_latency_ms"],
            )
        )

    async def _publish() -> None:
        from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

        producer = AIOKafkaProducer(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"])
        await producer.start()
        try:
            for e in events:
                await producer.send_and_wait(
                    RAG_RESPONSES_TOPIC, value=e.to_kafka_json(), key=e.app_trace_id.encode()
                )
        finally:
            await producer.stop()

    asyncio.run(_publish())
    return [
        {
            "ticker": e.ticker,
            "query": e.query,
            "sent_at_utc": e.timestamp_utc,
            "http_status": None,
            "source": f"constructed copy of real trace {source_trace_id}",
            "sampling_hash_decision_before_send": sampled,
            "app_trace_id": e.app_trace_id,
        }
        for e in events
    ]


def _rows(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def resolve_trace_ids(
    conn: psycopg.Connection[Any], sent: list[dict[str, Any]], since: str
) -> None:
    """Fill app_trace_id for requests whose response carried none (blocked or
    errored requests) from the persisted rag_events row for that exact query."""
    for item in sent:
        if item["app_trace_id"] is not None:
            continue
        rows = _rows(
            conn,
            "SELECT app_trace_id FROM rag_events WHERE query = %s AND timestamp_utc >= %s "
            "ORDER BY timestamp_utc DESC LIMIT 1",
            (item["query"], since),
        )
        item["app_trace_id"] = rows[0]["app_trace_id"] if rows else None


def observe(conn: psycopg.Connection[Any], trace_ids: list[str]) -> dict[str, dict[str, Any]]:
    events = _rows(
        conn,
        "SELECT app_trace_id, status, block_reason, error_kind, timestamp_utc FROM rag_events "
        "WHERE app_trace_id = ANY(%s)",
        (trace_ids,),
    )
    verdicts = _rows(
        conn,
        "SELECT app_trace_id, status, faithfulness_status, answer_relevance_status, "
        "context_relevance_status, timestamp_utc FROM judge_verdicts "
        "WHERE app_trace_id = ANY(%s) ORDER BY timestamp_utc",
        (trace_ids,),
    )
    frontier = _rows(
        conn,
        "SELECT app_trace_id, verdict, disagreement_classification, evaluation_ts AS timestamp_utc "
        "FROM rag_frontier_verdicts WHERE app_trace_id = ANY(%s)",
        (trace_ids,),
    )
    out: dict[str, dict[str, Any]] = {}
    for tid in trace_ids:
        ev = [e for e in events if e["app_trace_id"] == tid]
        out[tid] = {
            "rag_event_rows": len(ev),
            "rag_status": ev[0]["status"] if ev else None,
            "block_reason": ev[0]["block_reason"] if ev else None,
            "error_kind": ev[0]["error_kind"] if ev else None,
            "flash_verdict_rows": [
                {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in r.items()
                    if k != "app_trace_id"
                }
                for r in verdicts
                if r["app_trace_id"] == tid
            ],
            "frontier_rows": [
                {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in r.items()
                    if k != "app_trace_id"
                }
                for r in frontier
                if r["app_trace_id"] == tid
            ],
            "frontier_deterministically_sampled": should_sample_for_frontier(tid),
        }
    return out


def settled(obs: dict[str, dict[str, Any]]) -> bool:
    for o in obs.values():
        if o["rag_event_rows"] == 0 or not o["flash_verdict_rows"]:
            return False
        if (
            o["frontier_deterministically_sampled"]
            and o["rag_status"] == "success"
            and not o["frontier_rows"]
        ):
            return False
    return True


def public_state(trace_id: str) -> dict[str, Any]:
    d: dict[str, Any] = httpx.get(f"{GATEWAY}/ops/traces/{trace_id}", timeout=20).json()
    frontier = d.get("frontier") or {}
    return {
        "judge_state": d.get("judge_state"),
        "frontier_sampled": frontier.get("sampled"),
        "frontier_note": frontier.get("note"),
        "has_frontier_evidence": frontier.get("evidence") is not None,
    }


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--questions", help="start:stop slice of the fixed pool (gateway mode)")
    ap.add_argument("--candidate-of", help="real success trace id to copy (constructed mode)")
    ap.add_argument("--candidates", type=int, default=1)
    ap.add_argument("--sampled", choices=["yes", "no"], default="yes")
    ap.add_argument("--injection", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wait", type=int, default=240, help="seconds to wait for judges to settle")
    args = ap.parse_args()

    started = datetime.now(UTC).isoformat()
    with psycopg.connect(risingwave_dsn(), autocommit=True) as conn:
        if args.candidate_of:
            sent = publish_candidates(
                conn, args.candidate_of, args.candidates, args.sampled == "yes"
            )
            print(
                f"experiment {args.experiment} phase {args.phase}: {len(sent)} constructed events"
            )
        else:
            lo, hi = (int(x) for x in args.questions.split(":"))
            print(f"experiment {args.experiment} phase {args.phase}: {hi - lo} real queries")
            sent = send(QUESTIONS[lo:hi])
        deadline = time.monotonic() + args.wait
        while True:
            resolve_trace_ids(conn, sent, started)
            ids = [s["app_trace_id"] for s in sent if s["app_trace_id"]]
            obs = observe(conn, ids)
            if len(ids) == len(sent) and settled(obs):
                break
            if time.monotonic() > deadline:
                print("  wait budget spent before every trace settled; recording what exists")
                break
            time.sleep(5)
        time.sleep(15)  # catch late duplicates before counting rows
        obs = observe(conn, ids)

    for s in sent:
        tid = s["app_trace_id"]
        s["persisted"] = obs.get(tid) if tid else None
        s["public"] = public_state(tid) if tid else None

    delivered = [s for s in sent if s["persisted"] and s["persisted"]["rag_status"] == "success"]
    phase = {
        "phase": args.phase,
        "injection": args.injection,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "requests": len(sent),
        "delivered": len(delivered),
        "judge_state_counts": {},
        "requests_detail": sent,
    }
    counts: dict[str, int] = {}
    for s in sent:
        state = (s["public"] or {}).get("judge_state", "trace_not_found")
        counts[state] = counts.get(state, 0) + 1
    phase["judge_state_counts"] = counts

    out = Path(args.out)
    doc: dict[str, Any] = (
        json.loads(out.read_text())
        if out.exists()
        else {"experiment": args.experiment, "phases": []}
    )
    doc["phases"].append(phase)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, default=str))
    print(f"delivered {len(delivered)}/{len(sent)}; judge_state counts {counts}; wrote {out}")


if __name__ == "__main__":
    main()
