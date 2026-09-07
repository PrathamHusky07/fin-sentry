from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv()

app = FastAPI(title="fin-sentry gateway")

_DOWNSTREAM_URL: str = os.getenv("DOWNSTREAM_URL", "")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    if not _DOWNSTREAM_URL:
        return JSONResponse({"error": "DOWNSTREAM_URL not configured"}, status_code=503)

    body = await request.body()
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
