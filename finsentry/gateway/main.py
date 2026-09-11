from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry.trace import get_current_span
from pydantic import BaseModel, Field
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

from finsentry.events.producer import RagEventProducer
from finsentry.events.schema import RagResponseEvent
from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.rails import InputRailsAdapter
from finsentry.observability.tracing import get_tracer, set_app_trace_id
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
# Model routing identifier for the OpenAI-compatible downstream RAG server.
# For Ollama, this is the tag from `ollama list`. Do NOT confuse with GEMINI_MODEL.
# Empty default is intentional: a missing env var logs a WARNING at startup rather
# than silently sending a stale model name (e.g. "gemini-2.5-flash") to an Ollama server.
_DOWNSTREAM_MODEL_ROUTING_ID: str = os.getenv("DOWNSTREAM_MODEL", "").strip()

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
_tracer = get_tracer()

# Tenacity strategy for the 20-second total request budget.
# Module-level so tests can patch them without modifying retry logic.
_RAG_BUDGET: float = 20.0  # total wall-time budget per request in seconds
_RAG_STOP = stop_after_delay(20)
_RAG_WAIT = wait_exponential(multiplier=0.5, min=0.5, max=4)

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

    yield

    await _rag_event_producer.stop()


app = FastAPI(title="fin-sentry gateway", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
            return JSONResponse(
                {"error": "input rail service unavailable"}, status_code=503
            )

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


def _build_rag_messages(
    query: str, chunks: list[RetrievedChunk]
) -> list[dict[str, str]]:
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
) -> str:
    """Call the downstream LLM with a 20-second total request budget and circuit breaker.

    Returns the assistant message content string.

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

    # Established at handler entry so all observability across this request
    # (input rails, retrieval, downstream, output rails, event emit) shares
    # one stable correlation ID and a common start reference.
    app_trace_id = str(uuid.uuid4())
    request_start_time = time.monotonic()

    # app_trace_id (UUID4, 36 chars) and OTel trace_id (128-bit hex, 32 chars) serve
    # different audiences: app_trace_id correlates Kafka events, logs, and dashboards
    # without OTel participation; OTel trace_id is for the distributed tracing backend.
    # Recording app_trace_id on the active span links the two correlation systems.
    set_app_trace_id(get_current_span(), app_trace_id)

    query = request_body.query
    ticker = request_body.ticker
    top_k = request_body.top_k
    input_rail_status: Literal["pass", "modified", "blocked"] = "pass"

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
                return JSONResponse(
                    {"error": "input rail service unavailable"}, status_code=503
                )

            if status == RailStatus.BLOCKED:
                input_rail_status = "blocked"
                if _rag_event_producer is not None:
                    asyncio.create_task(
                        _rag_event_producer.emit(
                            RagResponseEvent(
                                event_id=str(uuid.uuid4()),
                                app_trace_id=app_trace_id,
                                timestamp_utc=datetime.now(UTC).isoformat(),
                                status="blocked",
                                endpoint="/v1/rag/query",
                                query=request_body.query,
                                ticker=ticker,
                                block_reason="input_rail_blocked",
                                block_rail=rail_name or "unknown",
                                input_rail_status="blocked",
                                total_latency_ms=int(
                                    (time.monotonic() - request_start_time) * 1000
                                ),
                            )
                        )
                    )
                block_body: dict[str, str] = {"error": "request blocked by input rail"}
                if rail_name is not None:
                    block_body["rail"] = rail_name
                return JSONResponse(block_body, status_code=403)

            if status == RailStatus.MODIFIED:
                input_rail_status = "modified"
                query = str(updated[0].get("content", query))

    # 2. Embed the (possibly sanitised) query.
    with _tracer.start_as_current_span("rag.embed_query"):
        embedding: list[float] = (
            await asyncio.to_thread(
                lambda: _embed_model.encode([query], show_progress_bar=False)
            )
        )[0].tolist()

    # 3. Retrieve top_k chunks via cosine similarity.
    with _tracer.start_as_current_span("rag.vector_search"):
        try:
            chunks = await _fetch_chunks(_DATABASE_URL, embedding, ticker, top_k)
        except Exception as exc:
            log.error("Vector search failed: %s", exc, exc_info=True)
            return JSONResponse({"error": "vector search failed"}, status_code=503)

    # 4. Retrieval rail: source-trust, injection detection, PII redaction.
    with _tracer.start_as_current_span("rag.retrieval_rail"):
        if _retrieval_rail is not None:
            filtered_chunks = await asyncio.to_thread(_retrieval_rail.check_chunks, chunks)
        else:
            filtered_chunks = chunks

    if not filtered_chunks:
        if _rag_event_producer is not None:
            asyncio.create_task(
                _rag_event_producer.emit(
                    RagResponseEvent(
                        event_id=str(uuid.uuid4()),
                        app_trace_id=app_trace_id,
                        timestamp_utc=datetime.now(UTC).isoformat(),
                        status="blocked",
                        endpoint="/v1/rag/query",
                        query=request_body.query,
                        ticker=ticker,
                        block_reason="no_trustworthy_sources",
                        block_rail="retrieval-rail",
                        input_rail_status=input_rail_status,
                        total_latency_ms=int(
                            (time.monotonic() - request_start_time) * 1000
                        ),
                    )
                )
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
    with _tracer.start_as_current_span("rag.downstream_llm"):
        try:
            answer = await _call_downstream_rag(
                prompt_messages, _DOWNSTREAM_URL, _rag_breaker
            )
        except _DownstreamCircuitOpenError as exc:
            return JSONResponse(
                {
                    "error": "downstream_circuit_open",
                    "retry_after": round(exc.retry_after, 1),
                },
                status_code=503,
            )
        except _NonRetryableError as exc:
            return JSONResponse(
                {"error": "bad request to downstream"}, status_code=exc.status_code
            )
        except _AuthError:
            return JSONResponse(
                {"error": "downstream auth misconfiguration"}, status_code=502
            )
        except RetryError as exc:
            last = exc.last_attempt.exception()
            if isinstance(last, _RateLimitError):
                return JSONResponse({"error": "downstream rate limit"}, status_code=429)
            return JSONResponse({"error": "downstream unavailable"}, status_code=504)
        except Exception as exc:
            log.error("Unexpected downstream error: %s", exc, exc_info=True)
            return JSONResponse({"error": "downstream error"}, status_code=502)

    # 7. Output rails: schema, regulated phrases, faithfulness.
    retrieved_chunk_ids = {c.chunk_id for c in filtered_chunks}
    # List forms used for event payloads (set above is used for citation cross-check).
    _ev_chunk_ids = [c.chunk_id for c in filtered_chunks]
    _ev_chunk_texts = [c.text for c in filtered_chunks]
    output_trace: dict[str, Any] = {}

    # Rail A: schema enforcement + citation cross-check
    with _tracer.start_as_current_span("rag.schema_rail"):
        if _schema_rail is not None:
            schema_decision = _schema_rail.check(answer, retrieved_chunk_ids)
            if schema_decision.outcome == "block":
                if _rag_event_producer is not None:
                    asyncio.create_task(
                        _rag_event_producer.emit(
                            RagResponseEvent(
                                event_id=str(uuid.uuid4()),
                                app_trace_id=app_trace_id,
                                timestamp_utc=datetime.now(UTC).isoformat(),
                                status="blocked",
                                endpoint="/v1/rag/query",
                                query=request_body.query,
                                ticker=ticker,
                                retrieved_chunk_ids=_ev_chunk_ids,
                                retrieved_chunks_text=_ev_chunk_texts,
                                block_reason=schema_decision.reason,
                                block_rail="schema-enforcement",
                                model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
                                input_rail_status=input_rail_status,
                                output_rail_trace_snapshot=output_trace,
                                total_latency_ms=int(
                                    (time.monotonic() - request_start_time) * 1000
                                ),
                            )
                        )
                    )
                return JSONResponse(
                    {
                        "error": "output_rail_block",
                        "rail": "schema-enforcement",
                        "reason": schema_decision.reason,
                        "details": schema_decision.details,
                    },
                    status_code=422,
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
                parsed_answer = RagAnswerResponse(
                    answer=answer, citations=[], confidence="low"
                )

    # Rail B: regulated-phrase blocklist (runs on answer text only)
    with _tracer.start_as_current_span("rag.phrase_rail"):
        if _phrase_rail is not None:
            phrase_decision = _phrase_rail.check(parsed_answer.answer)
            if phrase_decision.outcome == "block":
                if _rag_event_producer is not None:
                    asyncio.create_task(
                        _rag_event_producer.emit(
                            RagResponseEvent(
                                event_id=str(uuid.uuid4()),
                                app_trace_id=app_trace_id,
                                timestamp_utc=datetime.now(UTC).isoformat(),
                                status="blocked",
                                endpoint="/v1/rag/query",
                                query=request_body.query,
                                ticker=ticker,
                                retrieved_chunk_ids=_ev_chunk_ids,
                                retrieved_chunks_text=_ev_chunk_texts,
                                block_reason=phrase_decision.reason,
                                block_rail="regulated-phrases",
                                model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
                                input_rail_status=input_rail_status,
                                output_rail_trace_snapshot=output_trace,
                                total_latency_ms=int(
                                    (time.monotonic() - request_start_time) * 1000
                                ),
                            )
                        )
                    )
                return JSONResponse(
                    {
                        "error": "output_rail_block",
                        "rail": "regulated-phrases",
                        "reason": phrase_decision.reason,
                        "details": phrase_decision.details,
                    },
                    status_code=422,
                )
            output_trace["regulated-phrases"] = {
                "outcome": "pass",
                "reason": phrase_decision.reason,
            }

    # Rail C: faithfulness (async, fail-open per ADR 005)
    with _tracer.start_as_current_span("rag.faithfulness_rail"):
        if _faithfulness_rail is not None:
            faith_decision = await _faithfulness_rail.check(
                parsed_answer.answer, filtered_chunks
            )
            output_trace["faithfulness"] = faith_decision.details
            if faith_decision.outcome == "block":
                if _rag_event_producer is not None:
                    asyncio.create_task(
                        _rag_event_producer.emit(
                            RagResponseEvent(
                                event_id=str(uuid.uuid4()),
                                app_trace_id=app_trace_id,
                                timestamp_utc=datetime.now(UTC).isoformat(),
                                status="blocked",
                                endpoint="/v1/rag/query",
                                query=request_body.query,
                                ticker=ticker,
                                retrieved_chunk_ids=_ev_chunk_ids,
                                retrieved_chunks_text=_ev_chunk_texts,
                                block_reason=faith_decision.reason,
                                block_rail="faithfulness",
                                model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
                                input_rail_status=input_rail_status,
                                output_rail_trace_snapshot=output_trace,
                                total_latency_ms=int(
                                    (time.monotonic() - request_start_time) * 1000
                                ),
                            )
                        )
                    )
                return JSONResponse(
                    {
                        "error": "output_rail_block",
                        "rail": "faithfulness",
                        "reason": faith_decision.reason,
                        "details": faith_decision.details,
                    },
                    status_code=422,
                )

    if _rag_event_producer is not None:
        asyncio.create_task(
            _rag_event_producer.emit(
                RagResponseEvent(
                    event_id=str(uuid.uuid4()),
                    app_trace_id=app_trace_id,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    status="success",
                    endpoint="/v1/rag/query",
                    query=request_body.query,
                    ticker=ticker,
                    retrieved_chunk_ids=_ev_chunk_ids,
                    retrieved_chunks_text=_ev_chunk_texts,
                    answer=parsed_answer.answer,
                    citations=[c.model_dump() for c in parsed_answer.citations],
                    confidence=parsed_answer.confidence,
                    model_used=_DOWNSTREAM_MODEL_ROUTING_ID,
                    input_rail_status=input_rail_status,
                    output_rail_trace_snapshot=output_trace,
                    total_latency_ms=int((time.monotonic() - request_start_time) * 1000),
                )
            )
        )
    with _tracer.start_as_current_span("rag.build_response"):
        response = RagQueryResponse(
            answer=parsed_answer,
            retrieved_chunks=filtered_chunks,
            retrieval_trace_id=app_trace_id,
            output_rail_trace=output_trace,
        )
    return JSONResponse(response.model_dump())
