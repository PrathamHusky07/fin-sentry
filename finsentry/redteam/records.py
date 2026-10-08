"""
Persisted result shapes and request bodies for the Red Team API.

An ExecutionRecord is one scenario fired once. The scenario's `expected` is a copy
taken at execution time, next to the observed `outcome`, never merged with it.
Evidence is a plain JSON object of facts the executor measured; it never holds raw
model output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from finsentry.redteam.models import Category, Expectation, Expected, Mode, Outcome

ExecutionState = Literal["queued", "running", "finished"]
RunStatus = Literal["running", "completed", "failed"]

MAX_SCENARIOS_PER_RUN = 12


class ExecutionRecord(BaseModel):
    execution_id: str
    run_id: str
    seq: int
    scenario_id: str
    scenario_version: int
    category: Category
    target_layer: str
    mode: Mode
    expected: Expected
    state: ExecutionState
    outcome: Outcome | None
    acting_layer: str | None
    acting_check: str | None
    expectation: Expectation | None
    reason: str | None
    evidence: dict[str, object]
    trace_ref: str | None
    gemini_calls: int
    cost_usd: float
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class RunRecord(BaseModel):
    run_id: str
    created_at: datetime
    finished_at: datetime | None
    status: RunStatus
    scenario_ids: list[str]
    allow_judge_assisted: bool
    failure_reason: str | None
    total: int
    finished: int
    # Counts of finished executions by outcome. Derived from the rows, never stored.
    outcome_counts: dict[str, int]


class RunRequest(BaseModel):
    # None means every deterministic scenario. Judge-assisted ones are never implied.
    scenario_ids: list[str] | None = Field(default=None, max_length=MAX_SCENARIOS_PER_RUN)
    allow_judge_assisted: bool = False


class RunDetail(BaseModel):
    run: RunRecord
    executions: list[ExecutionRecord]


class ExecutionList(BaseModel):
    executions: list[ExecutionRecord]
    next_offset: int | None
