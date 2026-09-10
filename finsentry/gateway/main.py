from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker
from finsentry.gateway.rails import InputRailsAdapter
from finsentry.rails.input.llama_guard import LlamaGuard3Rail
from finsentry.rails.input.pii_redaction import PiiRedactionRail
from finsentry.rails.input.prompt_guard import PromptGuard2Rail

load_dotenv()

log = logging.getLogger(__name__)

_DOWNSTREAM_URL: str = os.getenv("DOWNSTREAM_URL", "")
_DATABASE_URL: str = os.getenv("DATABASE_URL", "")
_DEFAULT_RAG_MODEL = "gemini-2.5-flash"

_adapter: InputRailsAdapter | None = None
_embed_model: Any = None  # SentenceTransformer; ignore_missing_imports in mypy config
_rag_breaker: AsyncCircuitBreaker | None = None

# Tenacity strategy for the 20-second total request budget.
# Module-level so tests can patch them without modifying retry logic.
_RAG_STOP = stop_after_delay(20)
_RAG_WAIT = wait_exponential(multiplier=0.5, min=0.5, max=4)


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
    text: str
    similarity_score: float


class RagQueryResponse(BaseModel):
    answer: str
    retrieved_chunks: list[RetrievedChunk]
    retrieval_trace_id: str  # UUID for observability correlation


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
    global _adapter, _embed_model, _rag_breaker

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

    yield


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
            SELECT id, ticker, filing_type, filing_date::text, chunk_text,
                   1 - (embedding <=> %s::vector) AS similarity_score
            FROM corpus
            WHERE ticker = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params: tuple[Any, ...] = (vec, ticker, vec, top_k)
    else:
        sql = """
            SELECT id, ticker, filing_type, filing_date::text, chunk_text,
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
            similarity_score=float(row[5]),
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


def _build_rag_messages(
    query: str, chunks: list[RetrievedChunk]
) -> list[dict[str, str]]:
    system_msg = (
        "You are a financial research assistant. Answer questions using ONLY the provided "
        "document chunks. After each claim, cite the source chunk by writing [chunk_id] where "
        "chunk_id is the id of the chunk you drew from. If the chunks do not contain enough "
        "information to answer the question, say so explicitly."
    )
    chunks_text = "\n\n".join(
        f"[{i + 1}] chunk_id={c.chunk_id}, ticker={c.ticker}, "
        f"filing_type={c.filing_type}, date={c.filing_date}\n{c.text}"
        for i, c in enumerate(chunks)
    )
    user_msg = f"Question: {query}\n\nDocuments:\n{chunks_text}"
    return [
        {"role": "system", "content": system_msg},
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

    # Separate exception class per taxonomy entry so tenacity can distinguish
    # which ones to retry and the caller can read the last failure type.
    async def _attempt() -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            try:
                resp = await client.post(
                    f"{downstream_url}/v1/chat/completions",
                    json={
                        "model": _DEFAULT_RAG_MODEL,
                        "messages": prompt_messages,
                    },
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                await breaker.record_failure()
                raise _RetryableError(-1) from exc

        if resp.status_code in {400, 422}:
            raise _NonRetryableError(resp.status_code, resp.text)
        if resp.status_code in {401, 403}:
            raise _AuthError(resp.status_code)
        if resp.status_code == 429:
            # Rate limit: retry but do NOT increment breaker counter.
            raise _RateLimitError()
        if resp.status_code >= 500:
            await breaker.record_failure()
            raise _RetryableError(resp.status_code)

        resp.raise_for_status()
        await breaker.record_success()
        data: dict[str, Any] = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async for attempt in AsyncRetrying(
        stop=_RAG_STOP,
        wait=_RAG_WAIT,
        retry=retry_if_exception_type((_RetryableError, _RateLimitError)),
        reraise=False,
    ):
        with attempt:
            return await _attempt()

    # Unreachable: tenacity raises RetryError before exiting the loop.
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

    query = request_body.query
    ticker = request_body.ticker
    top_k = request_body.top_k

    # 1. Input rails on the query.
    if _adapter is not None:
        from nemoguardrails.rails.llm.options import RailStatus

        try:
            updated, status, rail_name, _explain = await _adapter.run(
                [{"role": "user", "content": query}]
            )
        except Exception as exc:
            log.error("Input rail enforcement failed: %s", exc, exc_info=True)
            return JSONResponse({"error": "input rail service unavailable"}, status_code=503)

        if status == RailStatus.BLOCKED:
            block_body: dict[str, str] = {"error": "request blocked by input rail"}
            if rail_name is not None:
                block_body["rail"] = rail_name
            return JSONResponse(block_body, status_code=403)

        if status == RailStatus.MODIFIED:
            query = str(updated[0].get("content", query))

    # 2. Embed the (possibly sanitised) query.
    embedding: list[float] = (
        await asyncio.to_thread(
            _embed_model.encode,
            [query],
            False,  # show_progress_bar
        )
    )[0].tolist()

    # 3. Retrieve top_k chunks via cosine similarity.
    try:
        chunks = await _fetch_chunks(_DATABASE_URL, embedding, ticker, top_k)
    except Exception as exc:
        log.error("Vector search failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "vector search failed"}, status_code=503)

    # 4. Assemble RAG prompt.
    prompt_messages = _build_rag_messages(query, chunks)

    # 5. Forward to downstream LLM with budget and circuit breaker.
    try:
        answer = await _call_downstream_rag(prompt_messages, _DOWNSTREAM_URL, _rag_breaker)
    except _DownstreamCircuitOpenError as exc:
        return JSONResponse(
            {
                "error": "downstream_circuit_open",
                "retry_after": round(exc.retry_after, 1),
            },
            status_code=503,
        )
    except _NonRetryableError as exc:
        return JSONResponse({"error": "bad request to downstream"}, status_code=exc.status_code)
    except _AuthError:
        return JSONResponse({"error": "downstream auth misconfiguration"}, status_code=502)
    except RetryError as exc:
        last = exc.last_attempt.exception()
        if isinstance(last, _RateLimitError):
            return JSONResponse({"error": "downstream rate limit"}, status_code=429)
        return JSONResponse({"error": "downstream unavailable"}, status_code=504)
    except Exception as exc:
        log.error("Unexpected downstream error: %s", exc, exc_info=True)
        return JSONResponse({"error": "downstream error"}, status_code=502)

    # 6. Return structured response.
    response = RagQueryResponse(
        answer=answer,
        retrieved_chunks=chunks,
        retrieval_trace_id=str(uuid.uuid4()),
    )
    return JSONResponse(response.model_dump())
