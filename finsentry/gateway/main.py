from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry.trace import StatusCode
from pydantic import BaseModel, Field
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

from finsentry.events.metrics_snapshot import MetricsSnapshot
from finsentry.events.producer import RagEventProducer
from finsentry.events.schema import RagResponseEvent
from finsentry.events.trace_api import (
    CalibrationHealthResponse,
    TraceDetailResponse,
    TraceListResponse,
)
from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.metrics_client import (
    fetch_calibration_health,
    fetch_trace_detail,
    fetch_trace_list,
)
from finsentry.gateway.metrics_poller import MetricsPoller
from finsentry.gateway.rails import InputRailsAdapter
from finsentry.observability.tracing import configure_tracer_provider, get_tracer, set_app_trace_id
from finsentry.rails.input.llama_guard import LlamaGuard3Rail
from finsentry.rails.input.pii_redaction import PiiRedactionRail
from finsentry.rails.input.prompt_guard import PromptGuard2Rail
from finsentry.rails.output.faithfulness import FaithfulnessRail, Mode
from finsentry.rails.output.guardrails_schema import SchemaEnforcementRail
from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail
from finsentry.rails.output.schema import RagAnswerResponse
from finsentry.rails.retrieval.rail import RetrievalRail

load_dotenv()

log = logging.getLogger(__name__)

_DOWNSTREAM_URL: str = os.getenv("DOWNSTREAM_URL", "")
_DATABASE_URL: str = os.getenv("DATABASE_URL", "")
# Day 8 Gate D: a minimal, non-business identifier for which replica served
# a request -- evidence for the nginx failover demo, not a product feature.
# Set explicitly per replica in docker-compose.dev.yml; falls back to a
# random suffix for any ad hoc single-process run (dev, tests).
_GATEWAY_INSTANCE_ID: str = os.getenv("GATEWAY_INSTANCE_ID") or f"gateway-{uuid.uuid4().hex[:8]}"
# Model routing identifier for the OpenAI-compatible downstream RAG server.
# For Ollama, this is the tag from `ollama list`. Do NOT confuse with GEMINI_MODEL.
# Empty default is intentional: a missing env var logs a WARNING at startup rather
# than silently sending a stale model name (e.g. "gemini-2.5-flash") to an Ollama server.
_DOWNSTREAM_MODEL_ROUTING_ID: str = os.getenv("DOWNSTREAM_MODEL", "").strip()
# Day 9 Session 2B: gates raw downstream-model-output logging on a schema-rail
# block (see the schema_rail_block warning below). OFF by default and in the
# demo configuration -- a reliability/compliance platform must not log raw
# model output, prompts, or retrieved context on the normal request path.
_DEV_DIAGNOSTIC_LOGS: bool = os.getenv("DEV_DIAGNOSTIC_LOGS", "") == "1"

if _DOWNSTREAM_URL and not _DOWNSTREAM_MODEL_ROUTING_ID:
    log.warning(
        "DOWNSTREAM_MODEL not set; the downstream RAG call will send an empty model field. "
        "Set DOWNSTREAM_MODEL to the Ollama tag (e.g. llama3.1:8b) or the vLLM model name."
    )

_adapter: InputRailsAdapter | None = None
_embed_model: Any = None  # SentenceTransformer; ignore_missing_imports in mypy config
_rag_breaker: AsyncCircuitBreaker | None = None
_retrieval_rail: RetrievalRail | None = None
_schema_rail: SchemaEnforcementRail | None = None
_phrase_rail: RegulatedPhraseRail | None = None
_faithfulness_rail: FaithfulnessRail | None = None
_rag_event_producer: RagEventProducer | None = None
_metrics_http_client: httpx.AsyncClient | None = None
_metrics_poller: MetricsPoller | None = None
_tracer = get_tracer()

# Tenacity strategy for the 20-second total request budget.
# Module-level so tests can patch them without modifying retry logic.
_RAG_BUDGET: float = 20.0  # total wall-time budget per request in seconds
_RAG_STOP = stop_after_delay(20)
_RAG_WAIT = wait_exponential(multiplier=0.5, min=0.5, max=4)

# Hard end-to-end limit for one /v1/rag/query request: input rails, retrieval, the
# downstream call (which keeps its own 20 s budget above), the output rails and the
# faithfulness rail. Enforced at the request boundary in rag_query. The faithfulness
# rail is told how much of this is left, so it still fails open instead of tripping it.
_REQUEST_DEADLINE: float = 60.0
_DEADLINE_MARGIN: float = 5.0

# Per-attempt httpx timeout cap. Combined with the remaining-budget check, this
# ensures a single slow attempt cannot consume the entire budget.
_ATTEMPT_CAP: float = 15.0


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RagQueryRequest(BaseModel):
    query: str
    ticker: str | None = None
    top_k: int = 5


class RetrievedChunk(BaseModel):
    chunk_id: str
    ticker: str
    filing_type: str
    filing_date: str  # ISO YYYY-MM-DD; empty string when not available in schema
    source_url: str = ""  # https://www.sec.gov/... or empty for corpora without URLs
    text: str
    similarity_score: float


class RagQueryResponse(BaseModel):
    answer: RagAnswerResponse
    retrieved_chunks: list[RetrievedChunk]
    retrieval_trace_id: str  # UUID for observability correlation
    output_rail_trace: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal exceptions for the failure taxonomy
# ---------------------------------------------------------------------------


class _DownstreamCircuitOpenError(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after


class _RetryableError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _RateLimitError(Exception):
    pass


class _NonRetryableError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body


class _AuthError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    global _adapter, _embed_model, _rag_breaker, _retrieval_rail
    global _schema_rail, _phrase_rail, _faithfulness_rail, _rag_event_producer
    global _metrics_http_client, _metrics_poller

    configure_tracer_provider(
        cast(Literal["console", "otlp", "none"], os.getenv("OTEL_EXPORTER", "none"))
    )

    if os.getenv("DOWNSTREAM_URL") and not os.getenv("DOWNSTREAM_MODEL"):
        log.warning(
            "DOWNSTREAM_URL is set but DOWNSTREAM_MODEL is empty. "
            "The downstream RAG call will fail. Set DOWNSTREAM_MODEL "
            "to the Ollama tag (e.g. 'llama3.1:8b') or vLLM model name."
        )

    # Load bge-small-en-v1.5 in a thread; ~130 MB download on first run, then
    # served from ~/.cache/huggingface/. Blocking, so off the event loop.
    from sentence_transformers import SentenceTransformer

    _embed_model = await asyncio.to_thread(SentenceTransformer, "BAAI/bge-small-en-v1.5")

    # Rails registered in cheapest-first order. Updated each build day.
    # Constructor raises on NeMo init failure — FastAPI will refuse to start
    # rather than running without enforcement.
    _adapter = InputRailsAdapter(
        rails=[
            PromptGuard2Rail(),  # 20-50 ms, CPU fp32
            PiiRedactionRail(),  # 30-80 ms, pattern recognizers only
            LlamaGuard3Rail(),  # 200-800 ms, 1B bfloat16
        ]
    )

    _rag_breaker = AsyncCircuitBreaker(
        failure_threshold=5,
        recovery_timeout=30.0,
        name="rag",
    )

    _retrieval_rail = RetrievalRail(db_url=_DATABASE_URL)

    _schema_rail = SchemaEnforcementRail()
    _phrase_rail = RegulatedPhraseRail()
    _faithfulness_rail = FaithfulnessRail(
        mode=cast(Mode, os.getenv("GEMINI_MODE", "disabled")),
        model_name=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        api_key=os.getenv("GEMINI_API_KEY"),
    )

    _rag_event_producer = RagEventProducer(
        mode=cast(Literal["kafka", "disabled"], os.getenv("KAFKA_MODE", "disabled")),
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    )
    await _rag_event_producer.start()

    # Day 8 Option C: the gateway never imports RisingWave. This poller's
    # only job is an httpx call to the metrics service's snapshot endpoint.
    _metrics_http_client = httpx.AsyncClient()
    _metrics_poller = MetricsPoller(_metrics_http_client)
    await _metrics_poller.start()

    yield

    await _metrics_poller.stop()
    await _metrics_http_client.aclose()
    await _rag_event_producer.stop()


app = FastAPI(title="fin-sentry gateway", lifespan=lifespan)

# Narrow local-dev CORS: the Next.js dev server (localhost:3000) is a
# different origin than the gateway (localhost:8000), so the browser needs
# this for both the RAG endpoints and the Day 8 SSE route. The deployed
# topology (Vercel frontend, nginx-fronted gateway replicas) has a different
# origin model entirely and is configured separately at deploy time, not here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "gateway_instance_id": _GATEWAY_INSTANCE_ID}


# ---------------------------------------------------------------------------
# Live Operations SSE (Day 8, Option C)
# ---------------------------------------------------------------------------

_SSE_KEEPALIVE_TIMEOUT_SECONDS = 15.0


async def _ops_stream_events(queue: asyncio.Queue[MetricsSnapshot]) -> AsyncGenerator[bytes]:
    """Relay every snapshot the poller broadcasts to this one SSE client,
    with a keep-alive comment if nothing arrives for a while. This is a
    snapshot relay, not an event log -- each frame is the full current
    state, not a delta."""
    try:
        while True:
            try:
                snapshot = await asyncio.wait_for(
                    queue.get(), timeout=_SSE_KEEPALIVE_TIMEOUT_SECONDS
                )
                yield f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n".encode()
            except TimeoutError:
                yield b": keep-alive\n\n"
    finally:
        if _metrics_poller is not None:
            _metrics_poller.unsubscribe(queue)


@app.get("/ops/stream")
async def ops_stream() -> Response:
    """SSE snapshot relay for the Live Operations route. One MetricsPoller
    per gateway process (started in lifespan, see above) serves every
    connection to this route -- this handler only subscribes a queue to it,
    it never polls the metrics service itself."""
    if _metrics_poller is None:
        return JSONResponse({"error": "metrics poller not initialised"}, status_code=503)

    queue = _metrics_poller.subscribe()
    return StreamingResponse(
        _ops_stream_events(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers proxied responses by default, which would hold
            # every SSE frame until the buffer fills -- defeating the point
            # of a live stream. This header is nginx-specific and ignored by
            # anything else that proxies this route.
            "X-Accel-Buffering": "no",
            # Day 8 Gate D failover evidence: which replica served this
            # connection, so a reconnect landing on a different replica is
            # provable, not asserted.
            "X-Gateway-Instance-Id": _GATEWAY_INSTANCE_ID,
        },
    )


# ---------------------------------------------------------------------------
# Trace investigation proxy (Day 9, Option C): the gateway stays the single
# browser-facing origin. These routes make an httpx call to the dashboard's
# internal /traces, /traces/{id}, /calibration/health routes -- the same
# mechanism as the Day 8 metrics poller, via METRICS_SERVICE_URL -- never
# importing dashboard functions or touching RisingWave directly.
# ---------------------------------------------------------------------------


@app.get("/ops/traces", response_model=TraceListResponse)
async def ops_traces(
    limit: int = 50,
    offset: int = 0,
    ticker: str | None = None,
    status: str | None = None,
    q: str | None = None,
    judge_state: str | None = None,
    frontier_sampled: bool | None = None,
    disagreement: bool | None = None,
) -> TraceListResponse:
    if _metrics_http_client is None:
        return JSONResponse({"error": "metrics client not initialised"}, status_code=503)  # type: ignore[return-value]
    try:
        return await fetch_trace_list(
            _metrics_http_client,
            limit,
            offset,
            ticker,
            status,
            q,
            judge_state,
            frontier_sampled,
            disagreement,
        )
    except httpx.HTTPError:
        log.warning("dashboard /traces unreachable", exc_info=True)
        return JSONResponse({"error": "metrics service unreachable"}, status_code=503)  # type: ignore[return-value]


@app.get("/ops/traces/{app_trace_id}", response_model=TraceDetailResponse)
async def ops_trace_detail(app_trace_id: str) -> TraceDetailResponse:
    if _metrics_http_client is None:
        return JSONResponse({"error": "metrics client not initialised"}, status_code=503)  # type: ignore[return-value]
    try:
        return await fetch_trace_detail(_metrics_http_client, app_trace_id)
    except httpx.HTTPError:
        log.warning("dashboard /traces/%s unreachable", app_trace_id, exc_info=True)
        return JSONResponse({"error": "metrics service unreachable"}, status_code=503)  # type: ignore[return-value]


@app.get("/ops/calibration/health", response_model=CalibrationHealthResponse)
async def ops_calibration_health() -> CalibrationHealthResponse:
    if _metrics_http_client is None:
        return JSONResponse({"error": "metrics client not initialised"}, status_code=503)  # type: ignore[return-value]
    try:
        return await fetch_calibration_health(_metrics_http_client)
    except httpx.HTTPError:
        log.warning("dashboard /calibration/health unreachable", exc_info=True)
        return JSONResponse({"error": "metrics service unreachable"}, status_code=503)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Chat completions proxy
# ---------------------------------------------------------------------------


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    if not _DOWNSTREAM_URL:
        return JSONResponse({"error": "DOWNSTREAM_URL not configured"}, status_code=503)

    body_json: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body_json.get("messages", [])

    if _adapter is not None:
        from nemoguardrails.rails.llm.options import RailStatus

        try:
            updated_messages, status, rail_name, _explain = await _adapter.run(messages)
        except Exception as exc:
            log.error("Input rail enforcement failed: %s", exc, exc_info=True)
            return JSONResponse({"error": "input rail service unavailable"}, status_code=503)

        if status == RailStatus.BLOCKED:
            block_body: dict[str, str] = {"error": "request blocked by input rail"}
            if rail_name is not None:
                block_body["rail"] = rail_name
            return JSONResponse(block_body, status_code=403)

        if status == RailStatus.MODIFIED:
            messages = updated_messages

        body_json = {**body_json, "messages": messages}

    body = json.dumps(body_json).encode()
    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in {"host", "content-length"}
    }

    async def _stream() -> AsyncGenerator[bytes]:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{_DOWNSTREAM_URL}/v1/chat/completions",
                content=body,
                headers=forward_headers,
                timeout=120.0,
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(_stream(), media_type="application/json")


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------


def _fetch_chunks_sync(
    db_url: str,
    query_embedding: list[float],
    ticker: str | None,
    top_k: int,
) -> list[RetrievedChunk]:
    """Sync psycopg call wrapped in asyncio.to_thread by _fetch_chunks."""
    import numpy as np
    from pgvector.psycopg import register_vector

    vec = np.array(query_embedding, dtype=np.float32)

    if ticker is not None:
        sql = """
            SELECT id, ticker, filing_type, filing_date::text, chunk_text, source_url,
                   1 - (embedding <=> %s::vector) AS similarity_score
            FROM corpus
            WHERE ticker = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params: tuple[Any, ...] = (vec, ticker, vec, top_k)
    else:
        sql = """
            SELECT id, ticker, filing_type, filing_date::text, chunk_text, source_url,
                   1 - (embedding <=> %s::vector) AS similarity_score
            FROM corpus
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params = (vec, vec, top_k)

    with psycopg.connect(db_url, autocommit=True) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows: list[Any] = cur.fetchall()

    return [
        RetrievedChunk(
            chunk_id=str(row[0]),
            ticker=str(row[1]),
            filing_type=str(row[2]),
            filing_date=str(row[3]) if row[3] is not None else "",
            text=str(row[4]),
            source_url=str(row[5]) if row[5] is not None else "",
            similarity_score=float(row[6]),
        )
        for row in rows
    ]


async def _fetch_chunks(
    db_url: str,
    query_embedding: list[float],
    ticker: str | None,
    top_k: int,
) -> list[RetrievedChunk]:
    """Retrieve top_k chunks by cosine similarity from pgvector."""
    return await asyncio.to_thread(_fetch_chunks_sync, db_url, query_embedding, ticker, top_k)


# ---------------------------------------------------------------------------
# Downstream LLM call with circuit breaker and 20-second budget
# ---------------------------------------------------------------------------


_RAG_SYSTEM_PROMPT = """\
You are a financial research assistant. Answer questions using ONLY the provided document chunks.

You MUST respond with a single valid JSON object matching this exact schema:
{
  "answer": "<your answer as a string>",
  "citations": [{"chunk_id": "<id from [chunk_id=...] label>", "quote": "<quote, max 300 chars>"}],
  "confidence": "<low|medium|high>"
}

Example response:
{
  "answer": "Apple's Q4 FY2024 revenue was $94.9 billion, driven primarily by iPhone sales.",
  "citations": [{"chunk_id": "abc-123", "quote": "Total net sales for Q4 2024 were $94.9 billion"}],
  "confidence": "high"
}

Rules:
- cite only chunk_ids that appear in the [chunk_id=...] labels below
- if the retrieved chunks do not contain enough information to answer the question, respond with \
an answer explaining what is missing, an empty citations list [], and confidence "low"
- do not invent facts not present in the chunks
- output ONLY the JSON object, no surrounding text"""


def _build_rag_messages(query: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    chunks_text = "\n\n".join(
        f"[chunk_id={c.chunk_id}] ticker={c.ticker}, "
        f"filing_type={c.filing_type}, date={c.filing_date}\n{c.text}"
        for c in chunks
    )
    user_msg = f"Question: {query}\n\nDocuments:\n{chunks_text}"
    return [
        {"role": "system", "content": _RAG_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


async def _call_downstream_rag(
    prompt_messages: list[dict[str, str]],
    downstream_url: str,
    breaker: AsyncCircuitBreaker,
    raw_body_out: list[str] | None = None,
) -> str:
    """Call the downstream LLM with a 20-second total request budget and circuit breaker.

    Returns the assistant message content string.

    If raw_body_out is given, the successful attempt's raw HTTP response text
    (resp.text, before any JSON parsing or field extraction) is appended to it.
    This lets callers inspect what the downstream actually sent even though
    this function returns only the extracted content string.

    Raises:
        _DownstreamCircuitOpenError: breaker is OPEN; caller returns 503.
        _NonRetryableError: downstream returned 400 or 422; caller forwards error.
        _AuthError: downstream returned 401 or 403; caller returns 502.
        RetryError (tenacity): budget exhausted; caller checks last exception type
            and returns 504 (or 429 if the last failure was a rate limit).
    """
    is_open, retry_after = await breaker.is_open()
    if is_open:
        raise _DownstreamCircuitOpenError(retry_after)

    # Absolute deadline for the entire request, including all retries and backoffs.
    # Two-layer enforcement: asyncio.wait_for (hard cancellation) + httpx.Timeout
    # (transport-level). See ADR 004 for rationale.
    deadline = time.monotonic() + _RAG_BUDGET

    # _attempt raises typed exceptions only; no breaker mutations here.
    # Breaker mutations happen exactly once at the retry-loop boundary so that
    # one logical request produces at most one counter increment.
    async def _attempt() -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RetryableError(-1)
        per_attempt_timeout = httpx.Timeout(min(_ATTEMPT_CAP, remaining))
        async with httpx.AsyncClient(timeout=per_attempt_timeout) as client:
            try:
                # Two-layer deadline enforcement (ADR 004):
                # Layer 1 — asyncio.wait_for provides an application-owned hard
                # cancellation boundary. httpx's read timeout is inactivity-based
                # (verified empirically), so a server that drip-feeds bytes can keep
                # the await alive past the nominal timeout. asyncio.wait_for cancels
                # the coroutine at the remaining-budget boundary regardless.
                # Layer 2 — httpx.Timeout(remaining) is the transport-level guard
                # for common fast-fail cases (refused, DNS, short stalls).
                resp = await asyncio.wait_for(
                    client.post(
                        f"{downstream_url}/v1/chat/completions",
                        json={
                            "model": _DOWNSTREAM_MODEL_ROUTING_ID,
                            "messages": prompt_messages,
                            # Constrain output to valid JSON at the decode layer (Ollama >=0.1.20).
                            # SchemaEnforcementRail still validates structure as defense-in-depth.
                            "format": "json",
                        },
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                raise _RetryableError(-1)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # httpx.TransportError covers ConnectError, ReadError, WriteError,
                # PoolTimeout, and RemoteProtocolError; all are retryable per ADR 004.
                raise _RetryableError(-1) from exc

        if resp.status_code in {400, 422}:
            raise _NonRetryableError(resp.status_code, resp.text)
        if resp.status_code in {401, 403}:
            raise _AuthError(resp.status_code)
        if resp.status_code == 429:
            # Rate limit: retry but do NOT increment breaker counter.
            raise _RateLimitError()
        if resp.status_code >= 500:
            raise _RetryableError(resp.status_code)

        resp.raise_for_status()
        if raw_body_out is not None:
            raw_body_out.append(resp.text)
        data: dict[str, Any] = resp.json()
        return str(data["choices"][0]["message"]["content"])

    def _budget_wait(retry_state: Any) -> float:
        # Clip the exponential backoff to whatever budget remains so that the
        # sleep itself cannot push the total elapsed time past the deadline.
        base = float(_RAG_WAIT(retry_state))
        remaining = deadline - time.monotonic()
        return max(0.0, min(base, remaining))

    try:
        async for attempt in AsyncRetrying(
            stop=_RAG_STOP,
            wait=_budget_wait,
            retry=retry_if_exception_type((_RetryableError, _RateLimitError)),
            reraise=False,
        ):
            with attempt:
                result = await _attempt()
                await breaker.record_success()
                return result
    except RetryError as exc:
        # One logical request = at most one breaker mutation.
        # 429 exhaustion means the downstream is alive (rate-limiting), not failing.
        last = exc.last_attempt.exception()
        if isinstance(last, _RetryableError):
            await breaker.record_failure()
        raise

    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# RAG endpoint
# ---------------------------------------------------------------------------


@dataclass
class _RequestState:
    """What the terminal event of one request needs, and the flag that keeps it
    to exactly one terminal event per request."""

    app_trace_id: str
    start: float
    raw_query: str
    ticker: str | None
    # The query as forwarded downstream, after any input-rail redaction. None until
    # the input rails have run, so an earlier event redacts raw_query itself.
    query: str | None = None
    input_rail_status: Literal["pass", "modified", "blocked"] = "pass"
    emitted: bool = False


_WITHHELD_QUERY = "[query withheld: redaction unavailable]"


async def _redact_for_persistence(text: str) -> str:
    """Presidio-redact a query that never reached the input-rail sanitizer (a block or
    failure before it ran). Fails closed: if redaction cannot run, no query is kept."""
    try:
        decision = await asyncio.to_thread(PiiRedactionRail().check, text, {})
    except Exception:
        log.warning("query redaction failed; withholding the query from the event", exc_info=True)
        return _WITHHELD_QUERY
    if decision.outcome == "sanitize":
        return str(decision.details["sanitized_content"])
    return text


async def _publish_terminal(
    producer: RagEventProducer,
    state: _RequestState,
    timestamp_utc: str,
    total_latency_ms: int,
    # Event fields vary by status; RagResponseEvent validates them.
    fields: dict[str, Any],
) -> None:
    query = (
        state.query if state.query is not None else await _redact_for_persistence(state.raw_query)
    )
    await producer.emit(
        RagResponseEvent(
            event_id=str(uuid.uuid4()),
            app_trace_id=state.app_trace_id,
            timestamp_utc=timestamp_utc,
            endpoint="/v1/rag/query",
            query=query,
            ticker=state.ticker,
            input_rail_status=state.input_rail_status,
            total_latency_ms=total_latency_ms,
            **fields,
        )
    )


def _emit_terminal(state: _RequestState, **fields: Any) -> None:
    """Schedule the one terminal event for this request, fire-and-forget. A request
    that already emitted its terminal event never emits a second one."""
    producer = _rag_event_producer
    if producer is None or state.emitted:
        return
    state.emitted = True
    asyncio.create_task(
        _publish_terminal(
            producer,
            state,
            datetime.now(UTC).isoformat(),
            int((time.monotonic() - state.start) * 1000),
            fields,
        )
    )


def _emit_error(state: _RequestState, error_kind: str, error_detail: str) -> None:
    _emit_terminal(state, status="error", error_kind=error_kind, error_detail=error_detail[:500])


def _output_rail_block(
    state: _RequestState,
    rail: str,
    reason: str,
    evidence: dict[str, Any],
    output_trace: dict[str, Any],
) -> Response:
    """Record an output-rail block and return the 422. The body carries only fixed
    identifiers. Rail details can echo the model's reply, so they stay out of it."""
    _emit_terminal(
        state,
        status="blocked",
        block_reason=reason,
        block_rail=rail,
        model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
        output_rail_trace_snapshot=output_trace,
        **evidence,
    )
    return JSONResponse(
        {
            "error": "output_rail_block",
            "rail": rail,
            "reason": reason,
            "app_trace_id": state.app_trace_id,
            "message": f"The answer was blocked by the {rail} output rail.",
        },
        status_code=422,
    )


@app.post("/v1/rag/query")
async def rag_query(request_body: RagQueryRequest) -> Response:
    if not _DOWNSTREAM_URL:
        return JSONResponse({"error": "DOWNSTREAM_URL not configured"}, status_code=503)
    if _embed_model is None:
        return JSONResponse({"error": "embedding model not loaded"}, status_code=503)
    if _rag_breaker is None:
        return JSONResponse({"error": "circuit breaker not initialised"}, status_code=503)
    if not _DATABASE_URL:
        return JSONResponse({"error": "DATABASE_URL not configured"}, status_code=503)

    with _tracer.start_as_current_span("rag.query.total") as root_span:
        # Established inside the root span so set_app_trace_id records on a recording span.
        app_trace_id = str(uuid.uuid4())
        state = _RequestState(
            app_trace_id=app_trace_id,
            start=time.monotonic(),
            raw_query=request_body.query,
            ticker=request_body.ticker,
        )

        # app_trace_id (UUID4, 36 chars) and OTel trace_id (128-bit hex, 32 chars) serve
        # different audiences: app_trace_id correlates Kafka events, logs, and dashboards
        # without OTel participation; OTel trace_id is for the distributed tracing backend.
        # Recording app_trace_id on the root span links the two correlation systems.
        set_app_trace_id(root_span, app_trace_id)

        try:
            # One deadline for the whole request, not for any single stage. Expiry cancels
            # the handler wherever it is waiting and lands in the except TimeoutError below.
            async with asyncio.timeout(_REQUEST_DEADLINE):
                try:
                    return await _rag_query_inner(request_body, state)
                except Exception as exc:
                    error_kind = type(exc).__name__
                    error_detail = str(exc)[:500]
                    _emit_error(state, error_kind, error_detail)
                    root_span.set_status(StatusCode.ERROR, f"{error_kind}: {error_detail}")
                    log.error("Unhandled exception in rag_query: %s", exc, exc_info=True)
                    return JSONResponse({"error": "internal server error"}, status_code=500)
        except TimeoutError:
            detail = f"request exceeded the {_REQUEST_DEADLINE:g} second deadline"
            _emit_error(state, "request_deadline_exceeded", detail)
            root_span.set_status(StatusCode.ERROR, detail)
            log.error("rag_query deadline exceeded app_trace_id=%s", app_trace_id)
            return JSONResponse(
                {"error": "request deadline exceeded", "app_trace_id": app_trace_id},
                status_code=504,
            )


async def _rag_query_inner(request_body: RagQueryRequest, state: _RequestState) -> Response:
    """Core RAG handler body. Called inside the rag.query.total root span."""
    app_trace_id = state.app_trace_id
    query = request_body.query
    ticker = request_body.ticker
    top_k = request_body.top_k

    # 1. Input rails on the query.
    if _adapter is not None:
        with _tracer.start_as_current_span("rag.input_rails"):
            from nemoguardrails.rails.llm.options import RailStatus

            try:
                updated, status, rail_name, _explain = await _adapter.run(
                    [{"role": "user", "content": query}]
                )
            except Exception as exc:
                log.error("Input rail enforcement failed: %s", exc, exc_info=True)
                _emit_error(state, "input_rail_service_unavailable", str(exc))
                return JSONResponse({"error": "input rail service unavailable"}, status_code=503)

            if status == RailStatus.BLOCKED:
                state.input_rail_status = "blocked"
                _emit_terminal(
                    state,
                    status="blocked",
                    block_reason="input_rail_blocked",
                    block_rail=rail_name or "unknown",
                )
                block_body: dict[str, str] = {"error": "request blocked by input rail"}
                if rail_name is not None:
                    block_body["rail"] = rail_name
                return JSONResponse(block_body, status_code=403)

            if status == RailStatus.MODIFIED:
                state.input_rail_status = "modified"
                query = str(updated[0].get("content", query))

    # From here on events carry the query the model sees, with any PII already redacted.
    state.query = query

    # 2. Embed the (possibly sanitised) query.
    with _tracer.start_as_current_span("rag.embed_query"):
        embedding: list[float] = (
            await asyncio.to_thread(lambda: _embed_model.encode([query], show_progress_bar=False))
        )[0].tolist()

    # 3. Retrieve top_k chunks via cosine similarity.
    with _tracer.start_as_current_span("rag.vector_search"):
        try:
            chunks = await _fetch_chunks(_DATABASE_URL, embedding, ticker, top_k)
        except Exception as exc:
            log.error("Vector search failed: %s", exc, exc_info=True)
            _emit_error(state, "vector_search_failed", str(exc))
            return JSONResponse({"error": "vector search failed"}, status_code=503)

    # 4. Retrieval rail: source-trust, injection detection, PII redaction.
    with _tracer.start_as_current_span("rag.retrieval_rail"):
        if _retrieval_rail is not None:
            filtered_chunks = await asyncio.to_thread(_retrieval_rail.check_chunks, chunks)
        else:
            filtered_chunks = chunks

    if not filtered_chunks:
        _emit_terminal(
            state,
            status="blocked",
            block_reason="no_trustworthy_sources",
            block_rail="retrieval-rail",
        )
        return JSONResponse(
            RagQueryResponse(
                answer=RagAnswerResponse(
                    answer="No trustworthy sources found for this query.",
                    citations=[],
                    confidence="low",
                ),
                retrieved_chunks=[],
                retrieval_trace_id=app_trace_id,
            ).model_dump()
        )

    # 5. Assemble RAG prompt.
    with _tracer.start_as_current_span("rag.assemble_prompt"):
        prompt_messages = _build_rag_messages(query, filtered_chunks)

    # 6. Forward to downstream LLM with budget and circuit breaker.
    # Evidence fields shared by every event from here on.
    evidence: dict[str, Any] = {
        "retrieved_chunk_ids": [c.chunk_id for c in filtered_chunks],
        "retrieved_chunks_text": [c.text for c in filtered_chunks],
    }
    # Set used for citation cross-check in schema rail.
    retrieved_chunk_ids = {c.chunk_id for c in filtered_chunks}

    with _tracer.start_as_current_span("rag.downstream_llm"):
        try:
            raw_body_holder: list[str] = []
            answer = await _call_downstream_rag(
                prompt_messages,
                _DOWNSTREAM_URL,
                _rag_breaker,  # type: ignore[arg-type]
                raw_body_holder,
            )
            raw_downstream_body = raw_body_holder[-1] if raw_body_holder else answer
        except _DownstreamCircuitOpenError as exc:
            _emit_error(
                state,
                "downstream_unavailable",
                f"circuit breaker open, retry after {round(exc.retry_after, 1)} s",
            )
            return JSONResponse(
                {
                    "error": "downstream_circuit_open",
                    "retry_after": round(exc.retry_after, 1),
                },
                status_code=503,
            )
        except _NonRetryableError as exc:
            _emit_error(
                state,
                "downstream_error",
                f"downstream rejected the request with status {exc.status_code}",
            )
            return JSONResponse({"error": "bad request to downstream"}, status_code=exc.status_code)
        except _AuthError as exc:
            _emit_error(
                state,
                "downstream_error",
                f"downstream auth misconfiguration, status {exc.status_code}",
            )
            return JSONResponse({"error": "downstream auth misconfiguration"}, status_code=502)
        except RetryError as exc:
            last = exc.last_attempt.exception()
            if isinstance(last, _RateLimitError):
                _emit_error(
                    state,
                    "downstream_rate_limit",
                    "downstream rate limit exhausted after retries",
                )
                return JSONResponse({"error": "downstream rate limit"}, status_code=429)
            _emit_error(state, "downstream_unavailable", "downstream unavailable after retries")
            return JSONResponse({"error": "downstream unavailable"}, status_code=504)
        except Exception as exc:
            log.error("Unexpected downstream error: %s", exc, exc_info=True)
            _emit_error(state, "downstream_error", str(exc))
            return JSONResponse({"error": "downstream error"}, status_code=502)

    # 7. Output rails: schema, regulated phrases, faithfulness.
    output_trace: dict[str, Any] = {}

    # Rail A: schema enforcement + citation cross-check
    with _tracer.start_as_current_span("rag.schema_rail"):
        if _schema_rail is not None:
            schema_decision = _schema_rail.check(answer, retrieved_chunk_ids)
            if schema_decision.outcome == "block":
                # Raw model output is never logged on the default path -- only
                # the non-sensitive diagnostic (reason, length, trace id). The
                # raw snippet is only added when DEV_DIAGNOSTIC_LOGS=1 is set
                # explicitly (local debugging), never in the demo configuration.
                if _DEV_DIAGNOSTIC_LOGS:
                    log.warning(
                        "schema_rail_block reason=%s raw_response_length=%d "
                        "raw_ollama_response_snippet=%r app_trace_id=%s",
                        schema_decision.reason,
                        len(raw_downstream_body),
                        raw_downstream_body[:500],
                        app_trace_id,
                        extra={
                            "rail": "schema-enforcement",
                            "reason": schema_decision.reason,
                            "raw_ollama_response_snippet": raw_downstream_body[:500],
                            "raw_response_length": len(raw_downstream_body),
                            "app_trace_id": app_trace_id,
                        },
                    )
                else:
                    log.warning(
                        "schema_rail_block reason=%s raw_response_length=%d app_trace_id=%s",
                        schema_decision.reason,
                        len(raw_downstream_body),
                        app_trace_id,
                        extra={
                            "rail": "schema-enforcement",
                            "reason": schema_decision.reason,
                            "raw_response_length": len(raw_downstream_body),
                            "app_trace_id": app_trace_id,
                        },
                    )
                return _output_rail_block(
                    state, "schema-enforcement", schema_decision.reason, evidence, output_trace
                )
            output_trace["schema-enforcement"] = {
                "outcome": "pass",
                "reason": schema_decision.reason,
            }
            # Parsed RagAnswerResponse is in schema_decision.details["parsed"]
            parsed_answer: RagAnswerResponse = schema_decision.details["parsed"]
        else:
            try:
                parsed_answer = RagAnswerResponse.model_validate_json(answer)
            except Exception:
                parsed_answer = RagAnswerResponse(answer=answer, citations=[], confidence="low")

    # Rail B: regulated-phrase blocklist (runs on answer text only)
    with _tracer.start_as_current_span("rag.phrase_rail"):
        if _phrase_rail is not None:
            phrase_decision = _phrase_rail.check(parsed_answer.answer)
            if phrase_decision.outcome == "block":
                return _output_rail_block(
                    state, "regulated-phrases", phrase_decision.reason, evidence, output_trace
                )
            output_trace["regulated-phrases"] = {
                "outcome": "pass",
                "reason": phrase_decision.reason,
            }

    # Rail C: faithfulness (async, fail-open per ADR 005)
    with _tracer.start_as_current_span("rag.faithfulness_rail"):
        if _faithfulness_rail is not None:
            # Hand the rail whatever is left of the request deadline, so a slow Gemini
            # makes it fail open (skipped_timeout) instead of failing the request.
            remaining = _REQUEST_DEADLINE - (time.monotonic() - state.start)
            faith_decision = await _faithfulness_rail.check(
                parsed_answer.answer,
                filtered_chunks,
                total_budget=max(1.0, remaining - _DEADLINE_MARGIN),
            )
            # The evaluator's raw reply is a debugging aid for the rail, not trace data.
            output_trace["faithfulness"] = {
                k: v for k, v in faith_decision.details.items() if k != "raw_response_snippet"
            }
            if faith_decision.outcome == "block":
                # A blocked answer is never persisted, so its claim text is not either.
                blocked_trace = {
                    **output_trace,
                    "faithfulness": {
                        k: v
                        for k, v in output_trace["faithfulness"].items()
                        if k not in {"supported_claims", "unsupported_claims"}
                    },
                }
                return _output_rail_block(
                    state, "faithfulness", faith_decision.reason, evidence, blocked_trace
                )

    # Build the response first: if that fails, the request is an error, not a success.
    with _tracer.start_as_current_span("rag.build_response"):
        response = RagQueryResponse(
            answer=parsed_answer,
            retrieved_chunks=filtered_chunks,
            retrieval_trace_id=app_trace_id,
            output_rail_trace=output_trace,
        )
        body = response.model_dump()
    _emit_terminal(
        state,
        status="success",
        answer=parsed_answer.answer,
        citations=[c.model_dump() for c in parsed_answer.citations],
        confidence=parsed_answer.confidence,
        model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
        output_rail_trace_snapshot=output_trace,
        **evidence,
    )
    return JSONResponse(body)
