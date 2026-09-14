# ADR 006 — Async Evaluation Pipeline: Producer Side

**Status**: Accepted
**Date**: 2026-09-11
**Deciders**: Prathamesh Kulkarni

## Context

Day 4A adds the gateway-side event emission layer for the async evaluation pipeline. Every
request that passes through `rag_query` emits a `RagResponseEvent` to a Redpanda topic.
Downstream consumers (Day 4B) read from that topic, score responses with the flash-tier
judge (Gemini), and persist scores to RisingWave for dashboard queries. This ADR records the
eight design decisions made on the producer side.

## Decision 1 — Single event topic, not per-lifecycle topics

One topic (`rag-responses`) carries all three lifecycle statuses: success, blocked, error.
Status is a first-class field in the event schema.

Note: the original draft used an underscore-separated form. Corrected to `rag-responses` (hyphen)
during the Day 4B closeout consolidation to match Redpanda topic naming conventions and the
`RAG_RESPONSES_TOPIC` constant in `finsentry/events/topics.py`.

**Alternatives considered**: separate topics per status (rag_blocked, rag_success, rag_error).

**Reason for rejection**: a single topic makes correlated queries simpler — "show everything
for request X" is a filter on app_trace_id rather than a multi-topic join. Per-status topics
add operational complexity (partition counts, retention policies, consumer group registrations)
without a throughput or isolation benefit at evaluation-event scale.

## Decision 2 — JSON serialization, not Avro or Protobuf

Events are serialized with Pydantic's `model_dump_json()` and deserialized with
`model_validate()`. No schema registry. No wire format beyond UTF-8 JSON.

**Reason**: evaluation events are low-volume (one per request) and consumed by a Python
judge worker that already has the Pydantic model. A schema registry adds operational
infrastructure and a language-coupling dependency with no practical benefit at this scale.
The migration path to Avro is a one-class adapter behind `RagEventProducer.emit()`.

## Decision 3 — aiokafka, not confluent-kafka

Pure Python async client. Matches FastAPI's async story. No C extension build dependency.

**Reason for rejecting confluent-kafka**: the C-bindings throughput advantage of
confluent-kafka matters at high throughput (millions of messages per second). Evaluation
events arrive at request rate — orders of magnitude below that threshold. The added build
complexity of C extensions is not justified. Migration path is a producer adapter swap.

## Decision 4 — Best-effort at-most-once delivery with `asyncio.create_task`

`rag_query` calls `asyncio.create_task(_rag_event_producer.emit(event))` and does not await
the task. The HTTP response is returned before the emit completes. Emit errors are logged at
WARNING and swallowed.

**Consequence**: events can be lost on process crash, event loop cancellation, or broker
unavailability. This is intentional. The evaluation pipeline is telemetry, not a financial
ledger. A lost event means a missing judge score for one request — the platform degrades
gracefully. Blocking the HTTP response on Kafka delivery would expose gateway latency to
broker health.

**Future path**: a transactional outbox pattern would give exactly-once delivery at the cost
of a Postgres write per request on the hot path.

## Decision 5 — KAFKA_MODE=disabled default with broker-unreachable fallback

`RagEventProducer` has two modes: `kafka` and `disabled`. The default is `disabled` so that
unit tests and local development without a running broker work with no extra configuration.
When mode is `kafka` and the broker is unreachable at startup, the producer self-transitions
to `disabled` and logs at ERROR — the gateway continues serving rather than refusing to start.

**Reason**: the gateway is the reliability platform. Its own event telemetry bus must not be
a single point of failure for request serving. Operator visibility comes from the ERROR log,
not from a crash.

## Decision 6 — app_trace_id distinct from OTel trace_id

`app_trace_id` is a UUID4 generated at handler entry, carried on every Kafka event, log line,
and OTel span attribute. The OTel `trace_id` is a 128-bit integer assigned by the
`TracerProvider`, formatted as 32 lowercase hex chars with no hyphens.

**Why two IDs**: OTel trace_id ties spans together in the distributed tracing backend and
propagates via W3C TraceContext headers. app_trace_id is the application-level correlation key
queryable in Kafka, Postgres, and log aggregators without OTel participation. They coexist:
app_trace_id appears as a span attribute on every OTel span, linking the two systems.

## Decision 7 — 10 named OTel spans in rag_query

`rag_query` creates 10 named child spans: `input_rails`, `embed_query`, `vector_search`,
`retrieval_rail`, `assemble_prompt`, `downstream_llm`, `schema_rail`, `phrase_rail`,
`faithfulness_rail`, `build_response`. Each wraps one logical operation using
`_tracer.start_as_current_span()` as a context manager.

FastAPI's OTel auto-instrumentation (when configured) provides the HTTP-level root span.
The application adds operation-level child spans for internal latency attribution. Setting
`app_trace_id` on `get_current_span()` at handler entry links the two correlation systems in
any active root span.

## Decision 8 — RisingWave v3.0.3 known crash is documented, not worked around

The docker-compose.dev.yml pins RisingWave v3.0.3 (playground mode). This release has a
known crash at approximately 5 hours of uptime in playground mode. The crash is a memory
issue in the single-process playground binary, not present in distributed deployments.

**Mitigation**: the `scripts/smoke_test_infra.py` script prints a WARNING when v3.0.x is
detected and instructs the operator to restart the container before long sessions. Day 4B
consumer work is expected to complete well within the 5-hour window per session. Upgrading
to a non-playground RisingWave deployment is deferred to a later day when persistent
materialized views justify the operational complexity.

## Decision 9 — Day 3 synchronous Faithfulness rail preserved as safety control

The spec preserves both roles for Faithfulness. Day 3 Faithfulness is a safety control
(output rail that can block a response with 422). Day 4 Flash tier is an asynchronous
evaluator (observability, does not block). Same metric name, different roles at different
points in the pipeline.

Day 4B does NOT delete the Day 3 sync rail. Day 4B does NOT create a synchronous fallback
that reinstates Faithfulness in the request path when the async plane is unavailable. If the
async plane is down, the dashboard shows the backlog and consumer lag; it does not silently
reintroduce Faithfulness in the request path.

This is the interview point that separates "we have Faithfulness twice" from "we have
Faithfulness at two distinct points in the pipeline defending against two different threat
models." The sync rail is a per-request admission gate with a latency cost. The async
evaluator is a continuous quality monitor with no latency cost to the caller.

## Decision 10 — "No trustworthy sources" emits status="blocked" while returning 200 to caller

The retrieval-rail short-circuit ("no chunks survived filtering") returns 200 OK to the
caller with a graceful-degradation response and simultaneously emits a status="blocked"
event to Kafka.

Two different perspectives on the same outcome: the caller sees successful graceful
degradation; the async evaluator sees a policy-driven block. This asymmetry is deliberate.
The caller-facing contract prioritizes availability. The observability contract records the
underlying policy decision. A downstream consumer can filter for status="blocked" with
block_rail="retrieval-rail" and see the full distribution of retrieval failures without the
caller ever receiving a 4xx or 5xx.

## Decision 11 — Redpanda dual-listener configuration for internal-vs-host client separation

During Day 4B empirical verification, RisingWave's CREATE SOURCE failed with
"Meta data fetch error / TimedOutQueue". Root cause: Day 1's compose file ran Redpanda in
`--mode dev-container` which advertises the Kafka API as `127.0.0.1:9092`. This works for
host clients using Docker port forwarding, but fails for in-Docker clients (RisingWave)
because `127.0.0.1` inside RisingWave's container refers to RisingWave itself.

Fix: dual-listener configuration. Redpanda now runs two Kafka listeners: INTERNAL on port
9092 advertising `redpanda:9092` for in-Docker traffic, and EXTERNAL on port 19092
advertising `localhost:19092` for host traffic. Configuration in `docker-compose.dev.yml`
via explicit `--kafka-addr` and `--advertise-kafka-addr` flags, dropping `--mode
dev-container`.

Consequences: host-side processes (gateway, consumer, dashboard) connect via
`localhost:19092`. In-Docker services (RisingWave sources) connect via `redpanda:9092`
(already the value in `infra/risingwave/init.sql`). `.env.example` updated to
`KAFKA_BOOTSTRAP_SERVERS=localhost:19092`. This is the standard Kafka production
pattern. Every Kafka deployment supporting mixed-network clients uses dual listeners.

## Consequences

- Gateway latency is not affected by Kafka broker health (fire-and-forget emit).
- Lost events during broker downtime are an accepted trade-off.
- KAFKA_MODE=disabled default enables test-without-infra by design.
- app_trace_id appears in Kafka events, OTel spans, and log lines — three observability
  surfaces share one stable correlation key per request.
- RisingWave v3.0.3 requires periodic container restart in long dev sessions.
- Day 3 sync Faithfulness rail and Day 4 async Flash judge coexist intentionally.
- Host-side processes connect to Redpanda via localhost:19092 (EXTERNAL listener).
- In-Docker processes (RisingWave) connect via redpanda:9092 (INTERNAL listener).
- Consumer lag is the signal for async plane health. No sync fallback is ever introduced.
