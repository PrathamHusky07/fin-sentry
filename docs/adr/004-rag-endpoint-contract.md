# ADR 004: RAG Endpoint Contract and Failure Semantics

**Date:** 2026-09-09
**Status:** Accepted

## Context

Day 3 of the build plan requires a reference RAG endpoint over the SEC EDGAR
corpus. The endpoint must expose the retrieval-generation boundary as a
structured trace so the Session B retrieval rail can inspect chunks before
they reach the generator.

The spec (lines 66-70) explicitly forbids reranking, hybrid retrieval, and
self-correction. The rationale is that a smarter retriever suppresses the
retrieval failures the reliability platform is designed to catch. The endpoint
must be deliberately basic.

The 10-company demo corpus contains real cross-ticker contamination risk
(JPMorgan 10-Ks dominate the chunk count at ~2730 chunks; a query without a
ticker filter will over-retrieve JPM), temporal mismatches (8-K chunks have no
period_of_report; older 10-Q chunks may answer questions about a different
fiscal period), and near-duplicate neighbors from overlapping section boilerplate
across annual filings. These are observable failure modes, not bugs to fix.

## Decision

### Endpoint contract

`POST /v1/rag/query` accepts:

```json
{ "query": "...", "ticker": "AAPL", "top_k": 5 }
```

`ticker` is optional. `top_k` defaults to 5. The response is:

```json
{
  "answer": "...",
  "retrieved_chunks": [
    {
      "chunk_id": "...",
      "ticker": "...",
      "filing_type": "...",
      "filing_date": "YYYY-MM-DD",
      "text": "...",
      "source_url": "https://www.sec.gov/...",
      "similarity_score": 0.87
    }
  ],
  "retrieval_trace_id": "<uuid>"
}
```

`filing_date` is always an ISO date string. The corpus schema has
`filing_date DATE NOT NULL`, so it is always present. The field is typed
`str` in the response model to accommodate future corpora that may not carry
a date; callers must not rely on it being parseable as a date.

`retrieval_trace_id` is a fresh UUID per request for OTel correlation.

### Retrieval implementation

Basic cosine vector search over the `corpus` pgvector table with the HNSW
index (`vector_cosine_ops`). The SQL with optional ticker filter:

```sql
SELECT id, ticker, filing_type, filing_date::text, chunk_text, source_url,
       1 - (embedding <=> %s::vector) AS similarity_score
FROM corpus
[WHERE ticker = %s]
ORDER BY embedding <=> %s::vector
LIMIT %s
```

No candidate over-retrieval, no reranking, no post-filtering, no temporal
handling. The top_k default of 5 is a natural demo default and not empirically
tuned; Session B's baseline diagnostic may surface retrieval quality evidence
that motivates a change.

Input rails run on the query before embedding. If a rail blocks, the endpoint
returns 403 without embedding or querying. If a rail sanitises the query (PII
redaction), the sanitised text is embedded and used downstream.

### Failure semantics

The downstream LLM call uses a 20-second total request budget enforced via
tenacity's `stop_after_delay(20)`. The budget is per-request, not per-attempt;
retries with exponential backoff (`multiplier=0.5, min=0.5s, max=4s`) continue
as long as elapsed time is under 20 seconds.

A circuit breaker (`AsyncCircuitBreaker`) sits in front of the downstream call,
one instance per endpoint. It trips after 5 consecutive failures and stays open
for 30 seconds. When open, all requests return 503 immediately with
`{"error": "downstream_circuit_open", "retry_after": <seconds>}`.

**Failure taxonomy -- what increments the failure counter and what does not:**

| Condition | Retry? | Increment breaker? |
|---|---|---|
| HTTP 500, 502, 503, 504 from downstream | Yes | Yes |
| Connection refused, reset, DNS failure (httpx.ConnectError) | Yes | Yes |
| Read-side transport failure (httpx.ReadError, httpx.RemoteProtocolError) | Yes | Yes |
| Any other httpx.TransportError subclass | Yes | Yes |
| httpx.TimeoutException on individual attempt | Yes | Yes |
| HTTP 400, 422 from downstream | No | No |
| HTTP 401, 403 from downstream | No | No |
| HTTP 429 from downstream | Yes | No |

**Rationale for the 400/422 distinction.** These status codes indicate the
caller sent a malformed request. The downstream is healthy. Retrying the same
payload produces the same error, so retrying wastes budget and the breaker
counter must not be incremented because there is no health signal.

**Rationale for the 401/403 distinction.** Auth failures indicate a
configuration problem on our side (wrong key, missing scope). The downstream
is healthy. The error is returned as 502 to the caller to signal downstream
misconfiguration rather than downstream unavailability.

**Rationale for the 429 distinction.** Rate limits confirm the downstream is
alive and processing requests; it is temporarily busy. Incrementing the breaker
on 429 would trip the breaker during a sustained traffic spike that the
downstream is correctly rate-limiting, causing 503 storms that are harder to
recover from than the 429 backpressure alone. If the 20-second budget expires
while retrying 429s, the caller receives 429 (not 504) so they can distinguish
"downstream throttled" from "downstream down".

**Rationale for request-level breaker semantics.** The circuit breaker counts
request-level outcomes, not attempt-level outcomes. A single logical request
that retries internally five times on 500 must not trip the breaker on itself;
five separate failed requests must. This is enforced by mutating breaker state
only at the retry-loop boundary, not inside individual attempts. `_attempt()`
raises typed exceptions only; the outer `try/except RetryError` block inspects
the last exception type and calls `record_failure()` exactly once per failed
request, and `record_success()` exactly once per successful request. A request
that exhausts its budget retrying 429s produces no breaker mutation because 429
exhaustion is a rate-limit outcome, not a health failure.

**Rationale for absolute deadline enforcement.** The 20-second budget is a
total wall-time contract, not a per-attempt guarantee. An absolute deadline is
recorded at request start (`deadline = time.monotonic() + _RAG_BUDGET`).

Two enforcement layers work together:

**Layer 1 (application-owned hard boundary)**: `asyncio.wait_for(client.post(...), timeout=remaining)`, where `remaining = deadline - time.monotonic()` at the start of each attempt. This layer provides a hard cancellation that does not depend on httpx semantics. When the timeout fires, `asyncio.wait_for` cancels the in-flight coroutine and raises `asyncio.TimeoutError`, which `_attempt()` converts to `_RetryableError`. This layer is necessary because httpx's read timeout is inactivity-based, not absolute wall-clock-based, as verified empirically: a server sending a byte every 100 ms can keep a 200 ms read timeout alive indefinitely, and `await client.post(...)` can therefore outlive the nominal deadline without an outer cancellation mechanism.

**Layer 2 (transport-level protection)**: `httpx.Timeout(min(_ATTEMPT_CAP, remaining))` on each `httpx.AsyncClient`. This catches common fast-fail cases before reaching the application-owned boundary: connection refused, DNS failure, and short stalls between response packets.

The exponential backoff sleep is clipped to `min(base_backoff, remaining)` so a pending sleep cannot push total elapsed past the deadline. A per-attempt timeout alone cannot provide the wall-clock guarantee: with a 15-second cap and two retries plus a 0.5-second backoff, total wall time can reach 30.5 seconds, a 10.5-second violation of the documented contract.

**Rationale for OPEN-state idempotence.** Once the breaker is OPEN, late-arriving
`record_failure()` calls from requests that were already in flight when the
breaker opened must not reset `_opened_at`. The 30-second recovery window is
anchored to the first transition to OPEN. If `_opened_at` were overwritten on
every failure call while OPEN, each late in-flight request would silently push
back the recovery timestamp, extending the outage window by seconds per request.
The fix guards the state transition with `if self._state != CircuitState.OPEN`,
so the OPEN transition and `_opened_at` assignment are both one-way.

## Alternatives Considered

**Reranking.** A cross-encoder reranker over the top-k candidates would improve
retrieval precision, particularly for queries that could match boilerplate from
multiple tickers. Rejected: the spec explicitly forbids it, and a smart reranker
would suppress the retrieval failures the reliability platform is designed to
detect and measure.

**Per-attempt timeout instead of total budget.** A 20-second per-attempt timeout
with 3 retries could produce up to 60 seconds of wall-clock latency. The
20-second total budget bounds the worst-case latency at the cost of fewer retry
opportunities if individual attempts are slow.

**Connection pool for vector search.** Using `psycopg_pool.AsyncConnectionPool`
would reduce connection overhead under concurrent load. Deferred: the demo
traffic is low, a per-request sync connection wrapped in `asyncio.to_thread`
is simpler and correct, and Session B's threshold work does not depend on
connection pool behavior.

## Consequences

Retrieval quality is intentionally not optimized. Cross-ticker contamination,
temporal mismatches, and near-duplicate neighbors are expected and will be
measurable in the Session B retrieval rail's baseline diagnostic. The platform's
value proposition is measuring and correcting these failure modes, not hiding them.

The retrieved_chunks list in the response is the retrieval-generation boundary trace exposed to callers. The retrieval rail operates inline within /v1/rag/query: after _fetch_chunks returns the top-k candidates and before _build_rag_messages assembles the LLM prompt. Only chunks that survive the retrieval rail's source-trust, injection, and PII checks are placed into the LLM prompt and returned in retrieved_chunks. If all chunks are dropped, the endpoint short-circuits and returns without calling the downstream LLM. Any change to the RetrievedChunk schema must be coordinated with the retrieval rail implementation in finsentry/rails/retrieval/rail.py.

**Rationale for pre-downstream latency contract.** The 20-second budget documented above applies to the downstream LLM call inside `_call_downstream_rag`. It does not include the input rails (Prompt Guard, Presidio, Llama Guard 3), query embedding, vector search, or the retrieval rail (per-chunk Prompt Guard + Presidio). On the current Apple Silicon MPS-inference deployment, the pre-downstream stages measure approximately 5 to 7 seconds per request (Llama Guard 3 dominates at approximately 3 seconds on MPS; the retrieval rail contributes approximately 250ms per chunk sequentially). Under a downstream-unavailable failure case, curl-visible request latency is approximately 5 to 7 seconds plus the 20-second budget plus approximately 2 seconds of framework overhead, totaling approximately 27 seconds. Under a healthy downstream, request latency is approximately 5 to 7 seconds plus downstream inference time. This is a documented characteristic of the current deployment topology, not a defect. Migrating Llama Guard 3 to a CUDA GPU deployment or moving retrieval-rail Prompt Guard calls to a batched inference path would reduce the pre-downstream contribution substantially; both are Phase 4 optimizations.
