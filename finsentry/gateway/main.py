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
from finsentry.rails.input.pii_redaction import PiiRedactionRail
from finsentry.rails.input.prompt_guard import PromptGuard2Rail

load_dotenv()

_DOWNSTREAM_URL: str = os.getenv("DOWNSTREAM_URL", "")
_adapter: InputRailsAdapter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _adapter
    # Rails registered in cheapest-first order. Updated each build day.
    _adapter = InputRailsAdapter(rails=[
        PromptGuard2Rail(),   # 20-50 ms, CPU fp32
        PiiRedactionRail(),   # 30-80 ms, pattern recognizers only
    ])
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
        messages, decisions = await _adapter.run(messages)
        blocked = next((d for d in decisions if d.outcome in ("block", "error")), None)
        if blocked is not None:
            status = 503 if blocked.outcome == "error" else 400
            return JSONResponse(
                {
                    "error": "request blocked by input rail",
                    "rail": blocked.reason,
                    "details": blocked.details,
                },
                status_code=status,
            )
        body_json = {**body_json, "messages": messages}

    body = json.dumps(body_json).encode()
    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length"}
    }

    async def _stream() -> AsyncGenerator[bytes, None]:
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
