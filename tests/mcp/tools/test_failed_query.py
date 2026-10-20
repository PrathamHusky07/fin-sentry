"""A failed query on a live pool reaches the caller as an error, never as an empty result.

The four tools that read rows used to return an empty result with risingwave_connected true
when their SQL failed, which no client could tell from no rows. They now raise, as
search_traces does. An offline pool still returns the empty result with the flag false, and a
query that ran and matched nothing still returns an empty result with the flag true.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from finsentry.mcp.state import dao
from finsentry.mcp.tools.injections import search_prompt_injections
from finsentry.mcp.tools.judges import get_judge_scores
from finsentry.mcp.tools.traces import explain_guardrail_decision, get_failing_traces
from finsentry.risingwave.dao import RisingWaveQueryError

CALLS: dict[str, Any] = {
    "get_failing_traces": lambda: get_failing_traces(failure_type="any"),
    "explain_guardrail_decision": lambda: explain_guardrail_decision("t1"),
    "get_judge_scores": lambda: get_judge_scores("t1"),
    "search_prompt_injections": lambda: search_prompt_injections(),
}


@pytest.fixture
def connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(type(dao), "connected", property(lambda self: True))


@pytest.mark.parametrize("tool", CALLS)
async def test_a_failed_query_on_a_live_pool_raises(
    tool: str, connected: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = AsyncMock(side_effect=RisingWaveQueryError("RisingWave query failed"))
    monkeypatch.setattr(dao, "query_all", failing)
    monkeypatch.setattr(dao, "query_one", failing)
    with pytest.raises(RisingWaveQueryError):
        await CALLS[tool]()


@pytest.mark.parametrize("tool", CALLS)
async def test_a_query_that_matched_nothing_is_an_empty_result_with_the_pool_connected(
    tool: str, connected: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dao, "query_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(dao, "query_one", AsyncMock(return_value=None))
    result = await CALLS[tool]()
    assert result.risingwave_connected is True


@pytest.mark.parametrize("tool", CALLS)
async def test_an_offline_pool_still_returns_an_empty_result_flagged_disconnected(
    tool: str,
) -> None:
    assert dao.connected is False  # no pool is open in the unit tests
    result = await CALLS[tool]()
    assert result.risingwave_connected is False
