from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from finsentry.gateway.rails import InputRailsAdapter
from finsentry.rails.input.llama_guard import LlamaGuard3Rail
from finsentry.rails.input.pii_redaction import PiiRedactionRail
from finsentry.rails.input.prompt_guard import PromptGuard2Rail

load_dotenv()

_DOWNSTREAM_URL: str = os.getenv("DOWNSTREAM_URL", "")
_adapter: InputRailsAdapter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    global _adapter
    # Rails registered in cheapest-first order. Updated each build day.
    _adapter = InputRailsAdapter(
        rails=[
            PromptGuard2Rail(),  # 20-50 ms, CPU fp32
            PiiRedactionRail(),  # 30-80 ms, pattern recognizers only
            LlamaGuard3Rail(),  # 500-1500 ms, 8B NF4 quantized
        ]
    )
    yield


app = FastAPI(title="fin-sentry gateway", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    if not _DOWNSTREAM_URL:
        return JSONResponse({"error": "DOWNSTREAM_URL not configured"}, status_code=503)

    body_json: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body_json.get("messages", [])

    if _adapter is not None:
        from nemoguardrails.rails.llm.options import RailStatus

        content, status, _explain = await _adapter.run(messages)

        if status == RailStatus.BLOCKED:
            return JSONResponse(
                {"error": "request blocked by input rail"},
                status_code=403,
            )

        if status == RailStatus.MODIFIED:
            messages = [
                {**m, "content": content} if m.get("role") == "user" else m for m in messages
            ]

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
