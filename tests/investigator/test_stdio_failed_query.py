"""Empty, unavailable, rejected and backend failure, told apart over the real MCP stdio server.

The server runs as a subprocess through its real entrypoint and the investigator reaches it
with the official SDK client, so nothing here is in-process. Its RisingWave connection is
pointed at two scratch databases on the local Postgres, which speaks the same wire protocol:

- a database with the tables and no rows, so a query succeeds and matches nothing;
- a database with no tables, so a query fails with a real SQL error on a live pool.

The scratch databases are created and dropped by the test. Nothing shared is read or written,
and no service configuration is changed. The test is skipped when that Postgres is not up.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import psycopg
import pytest
from mcp import StdioServerParameters

from finsentry.investigator.adapter import FETCH_ALL_TOOLS, ReadOnlyAdapter
from finsentry.investigator.contracts import TOOL_NAMES
from finsentry.investigator.mcp_client import PROJECT_ROOT, connect_read_tools

ADMIN_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/finsentry_test"
)

RAG_EVENTS = """CREATE TABLE rag_events (
    app_trace_id text, status text, endpoint text, ticker text, timestamp_utc timestamptz,
    block_reason text, block_rail text, error_kind text, error_detail text,
    input_rail_status text, output_rail_trace_snapshot jsonb)"""
JUDGE_VERDICTS = """CREATE TABLE judge_verdicts (
    app_trace_id text, status text, timestamp_utc timestamptz, total_gemini_calls int,
    answer_relevance_score float8, context_relevance_score float8, judge_tier text,
    judge_model text, faithfulness_score float8, faithfulness_status text,
    answer_relevance_status text, context_relevance_status text, total_input_tokens int,
    total_output_tokens int, total_thoughts_tokens int, total_cost_usd float8,
    evaluation_latency_ms int)"""

ROW_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("get_failing_traces", {"failure_type": "blocked", "time_window_minutes": 60}),
    ("explain_guardrail_decision", {"app_trace_id": "t1"}),
    ("get_judge_scores", {"app_trace_id": "t1"}),
    ("search_prompt_injections", {"time_window_minutes": 60}),
]


def _admin() -> psycopg.Connection[Any]:
    parts = urlparse(ADMIN_URL)
    dsn = ADMIN_URL.replace(parts.path, "/postgres")
    return psycopg.connect(dsn, autocommit=True, connect_timeout=5)


def _server(database: str, *, port: str | None = None) -> StdioServerParameters:
    parts = urlparse(ADMIN_URL)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "finsentry.mcp.server"],
        env={
            "OTEL_EXPORTER": "none",
            "RISINGWAVE_HOST": parts.hostname or "localhost",
            "RISINGWAVE_PORT": port or str(parts.port or 5432),
            "RISINGWAVE_USER": parts.username or "postgres",
            "RISINGWAVE_DB": database,
            "PGPASSWORD": parts.password or "",
            "DATABASE_URL": "",  # no Red Team store, and an empty value is not overridden
        },
        cwd=PROJECT_ROOT,
    )


@pytest.fixture(scope="module")
def scratch() -> Iterator[dict[str, str]]:
    suffix = uuid.uuid4().hex[:8]
    names = {"empty": f"fs_stdio_empty_{suffix}", "missing": f"fs_stdio_missing_{suffix}"}
    try:
        admin = _admin()
    except psycopg.OperationalError as exc:
        pytest.skip(f"the local Postgres is not reachable: {exc}")
    try:
        for name in names.values():
            admin.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
        parts = urlparse(ADMIN_URL)
        dsn = ADMIN_URL.replace(parts.path, f"/{names['empty']}")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(RAG_EVENTS)
            conn.execute(JUDGE_VERDICTS)
        yield names
    finally:
        for name in names.values():
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


@pytest.mark.parametrize("tool, args", ROW_TOOLS, ids=[t for t, _ in ROW_TOOLS])
async def test_a_query_that_matched_nothing_is_a_verified_empty(
    scratch: dict[str, str], tool: str, args: dict[str, Any]
) -> None:
    async with connect_read_tools(_server(scratch["empty"])) as tools:
        result = await ReadOnlyAdapter(tools).call(tool, "q1", **args)  # type: ignore[arg-type]
    assert result.status == "empty", result.error
    assert result.empty_unverified is False
    assert [e.kind for e in result.evidence] == ["query_result"]


@pytest.mark.parametrize("tool, args", ROW_TOOLS, ids=[t for t, _ in ROW_TOOLS])
async def test_a_failed_query_on_a_live_pool_is_unavailable(
    scratch: dict[str, str], tool: str, args: dict[str, Any]
) -> None:
    async with connect_read_tools(_server(scratch["missing"])) as tools:
        result = await ReadOnlyAdapter(tools).call(tool, "q1", **args)  # type: ignore[arg-type]
    assert result.status == "unavailable", result
    assert result.empty_unverified is False
    assert result.evidence == []


async def test_rows_that_exist_come_back_ok_and_a_backend_failure_in_a_raising_tool_is_unavailable(
    scratch: dict[str, str],
) -> None:
    parts = urlparse(ADMIN_URL)
    dsn = ADMIN_URL.replace(parts.path, f"/{scratch['empty']}")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO rag_events (app_trace_id, status, timestamp_utc, block_rail) "
            "VALUES ('blocked-1', 'blocked', NOW(), 'faithfulness')"
        )
    async with connect_read_tools(_server(scratch["empty"])) as tools:
        adapter = ReadOnlyAdapter(tools)
        rows = await adapter.call("get_failing_traces", "q1", failure_type="blocked")
        assert rows.status == "ok"
        assert [e.record_id for e in rows.evidence if e.kind == "trace"] == ["blocked-1"]
    async with connect_read_tools(_server(scratch["missing"])) as tools:
        failed = await ReadOnlyAdapter(tools).call("get_trace_detail", "q2", app_trace_id="x")
    assert failed.status == "unavailable"


async def test_a_malformed_call_is_rejected_and_an_unset_store_is_unavailable(
    scratch: dict[str, str],
) -> None:
    async with connect_read_tools(_server(scratch["empty"])) as tools:
        adapter = ReadOnlyAdapter(tools)
        bad_limit = await adapter.call("get_failing_traces", "q1", limit=0)
        no_store = await adapter.call("list_red_team_executions", "q2", limit=5)
        surface = {name for name in TOOL_NAMES}
    assert bad_limit.status == "rejected" and bad_limit.evidence == []
    assert no_store.status == "unavailable"
    assert FETCH_ALL_TOOLS <= surface and len(surface) == 9


async def test_an_offline_pool_stays_unavailable_over_stdio(scratch: dict[str, str]) -> None:
    """Nothing listens on port 1, so the server's pool never opens. psycopg_pool retries for
    about 30 s before the server falls back to offline mode."""
    async with connect_read_tools(_server(scratch["empty"], port="1")) as tools:
        result = await ReadOnlyAdapter(tools).call("get_judge_scores", "q1", app_trace_id="t1")
    assert result.status == "unavailable" and result.empty_unverified is False
