"""Shared builders for the red team tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI

from finsentry.events.trace_api import TraceDetailResponse
from finsentry.redteam.deps import Deps
from finsentry.redteam.models import Scenario
from finsentry.redteam.registry import get_scenario
from tests.conftest import TEST_DATABASE_URL


def scenario(scenario_id: str) -> Scenario:
    found = get_scenario(scenario_id)
    assert found is not None, scenario_id
    return found


def make_deps(**overrides: object) -> Deps:
    base: dict[str, object] = {
        "app": FastAPI(),
        "database_url": TEST_DATABASE_URL,
        "input_adapter": None,
        "retrieval_rail": None,
        "schema_rail": None,
        "phrase_rail": None,
        "faithfulness_rail": None,
        "metrics_client": None,
    }
    base.update(overrides)
    return Deps(**base)  # type: ignore[arg-type]


def trace(
    rag_status: str = "blocked",
    block_rail: str | None = "prompt-guard-2",
    query: str = "stored query",
    trace_id: str = "11111111-2222-3333-4444-555555555555",
) -> TraceDetailResponse:
    """The few TraceDetailResponse fields the executor reads."""
    return cast(
        TraceDetailResponse,
        SimpleNamespace(
            found=True,
            app_trace_id=trace_id,
            rag_status=rag_status,
            block_rail=block_rail,
            query=query,
        ),
    )
