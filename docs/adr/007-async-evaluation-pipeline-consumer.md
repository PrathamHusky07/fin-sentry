# ADR 007 — Async Evaluation Pipeline: Consumer, FlashJudge, and Dashboard

**Status:** Accepted  
**Date:** 2026-09-11  
**Context:** Day 4B build session — consumer-side of the evaluation pipeline

## Context

ADR 006 defined the producer side: how the gateway emits RagResponseEvents to
Redpanda. This ADR defines the consumer side: how the FlashJudge consumer
reads those events, scores them across three quality metrics, and makes the
verdicts observable through the dashboard.

The architecture has three components:

1. **RagEventConsumer** — an aiokafka consumer that reads `rag-responses`,
   enforces bounded concurrency, and calls the FlashJudge handler.
2. **FlashJudge** — an orchestrator that runs Faithfulness, AnswerRelevance,
   and ContextRelevance in parallel via asyncio.gather and emits a
   JudgeVerdictEvent to `judge-verdicts`.
3. **Dashboard** — a FastAPI app on port 8081 that queries five RisingWave
   materialized views and renders quality metrics plus consumer lag.

## Decisions

### Decision 1: asyncio.Semaphore(5) for bounded concurrency

Each Gemini call takes 10-30 seconds. Without a concurrency bound, a traffic
spike would queue hundreds of in-flight coroutines, exhausting memory and
defeating the per-request CostBudget. Semaphore(5) caps the concurrent
FlashJudge evaluations. The value 5 is chosen to match the Gemini free-tier
throughput (60 RPM / 12s per 3-call evaluation chain = ~5 concurrent chains).
This is a configuration parameter, not an architectural constant.

### Decision 2: Per-evaluation CostBudget (not per-session)

FlashJudge creates a fresh CostBudget for each RagResponseEvent. A shared
budget across evaluations would mean that a large event (with many chunks)
starves subsequent events. Per-evaluation isolation is the correct scope
because each event is an independent billing unit. The shared CostBudget
accumulates across the Faithfulness + AnswerRelevance + ContextRelevance calls
within one evaluation.

### Decision 3: asyncio.gather for the three metrics

The three metrics are independent of each other. Running them sequentially
adds ~90s per evaluation in the worst case (3 metrics x 30s timeout each).
asyncio.gather runs them concurrently and respects the Semaphore at the
evaluation level, not at the per-metric level. A metric that raises an
exception is caught individually; the others complete normally.

### Decision 4: JudgeVerdictEvent carries nullable scores, not a sentinel float

If a metric is skipped (any `skipped_*` status), its score field is `None`,
not 0.0 or -1.0. This preserves the semantic distinction between "the model
produced a score of 0.0" and "the evaluator was unavailable." The RisingWave
materialized views filter on `IS NOT NULL` so skipped events do not dilute
the aggregate averages.

### Decision 5: schema_version guard drops unknown versions without crashing

The consumer checks `schema_version == "1.0"` before deserializing. Unknown
versions are logged at WARNING and dropped via commit, not rejected. This
allows the producer to deploy a schema upgrade without requiring the consumer
to be upgraded atomically. The window during which the consumer drops events
is bounded by the consumer's deployment lag, not by schema incompatibility.

### Decision 6: Commit after handler completion, not before

Kafka offset commit happens after the FlashJudge handler completes, not when
the message is received. This means a crash during judgment causes the message
to be re-delivered after restart. The re-delivery window is bounded by the
consumer's restart time. Committing before handling would silently skip events
on crash, which is worse than re-processing them.

### Decision 7: Dashboard uses asyncpg pool against RisingWave

RisingWave exposes the PostgreSQL wire protocol on port 4566. asyncpg provides
a connection pool with async support. The dashboard does not use psycopg2 or
a sync DBAPI because those would block the FastAPI event loop. The pool is
initialized in the FastAPI lifespan context manager and closed on shutdown.

### Decision 8: Dashboard renders gracefully when RisingWave is unreachable

If asyncpg fails to connect at startup, `_pool` is set to None and all metric
queries return None. The HTML template renders "—" for every metric card.
This is intentional: the dashboard is a monitoring tool, not a control plane.
An offline dashboard should not block the gateway or the consumer.

### Decision 9: Consumer lag monitor uses Redpanda Admin HTTP API

The Redpanda Admin API (port 9644) exposes consumer group offsets via HTTP
without requiring a Kafka protocol connection. This keeps the monitor
dependency-free: a plain httpx GET request returns the lag per partition. The
monitor is polled on each dashboard request, not on a background schedule,
so the lag reflects the state at render time.

### Decision 10: Non-success events (blocked, error) are not scored

FlashJudge only evaluates events with `status == "success"` and a non-empty
`answer`. Blocked events have no generated answer to score for faithfulness or
relevance. Error events may have partial data. Scoring them would produce
meaningless metrics. The JudgeVerdictEvent for a non-success source event
carries `skipped_non_success` for all three metric status fields.
