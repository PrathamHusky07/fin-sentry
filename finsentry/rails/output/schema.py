from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str
    quote: str = Field(max_length=300)


class RagAnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: Literal["low", "medium", "high"]
