"""
A recovery rehearsal: restore the committed archive into a disposable environment and prove
the application can read it back, without touching the development database, the live
topics or a model.

Everything this module creates carries a random token and is dropped afterwards:

- a Postgres database named finsentry_recovery_<token>, migrated and filled by the real
  migrator and the real materialize();
- a RisingWave database of the same name, built from infra/risingwave/init.sql with its
  three topic names rewritten to recovery-<token>-<topic>;
- those three replay topics in Redpanda, filled by republish(). No consumer subscribes to
  a topic with that name, so no event on them is judged and no Gemini call is made.

The checks run against those copies only. The development Postgres, the three live topics
and the archive directory are read or left alone, never written.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import psycopg
from fastapi import FastAPI

from finsentry.archive.export import ROOT, TABLE_ORDER, TOPICS
from finsentry.archive.format import MANIFEST, read_lines
from finsentry.archive.restore import materialize, republish
from finsentry.db import migrate

PREFIX = "finsentry_recovery_"
INIT_SQL = ROOT / "infra" / "risingwave" / "init.sql"
SOURCES = {
    "rag-responses": "rag_events",
    "judge-verdicts": "judge_verdicts",
    "rag-frontier-verdicts": "rag_frontier_verdicts",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _database_url(base_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?|$)", rf"/{name}\1", base_url, count=1)


def _checked_name(name: str) -> str:
    """Only a name this module made can be created or dropped, so a typo can never point a
    DROP DATABASE at the development or test database."""
    if not re.fullmatch(rf"{PREFIX}[0-9a-f]{{8}}", name):
        raise ValueError(f"{name} is not a recovery database name")
    return name


def _expected(directory: Path) -> dict[str, int]:
    manifest = json.loads((directory / MANIFEST).read_text("utf-8"))
    return {name: int(entry["records"]) for name, entry in manifest["datasets"].items()}


def _scalar(conn: psycopg.Connection[Any], sql: str, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def postgres_checks(directory: Path, url: str) -> list[Check]:
    """Restore into the disposable Postgres database `url` and verify it."""
    expected = _expected(directory)
    migrate.run(url)
    first = materialize(directory, url)
    checks = [
        Check(
            "restore inserts every archived record",
            first == expected,
            ", ".join(f"{k} {v}" for k, v in first.items()),
        )
    ]
    with psycopg.connect(url) as conn:
        for table in TABLE_ORDER:
            archived = set(
                (directory / "postgres" / f"{table}.jsonl").read_text("utf-8").splitlines()
            )
            restored = {
                r[0]
                for r in conn.execute(f"SELECT to_jsonb(t)::text FROM {table} t")  # noqa: S608
            }
            checks.append(
                Check(
                    f"{table} rows are byte-identical to the archive",
                    restored == archived,
                    f"{len(restored)} rows",
                )
            )
        fks = _scalar(
            conn,
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND conrelid IN"
            " ('red_team_executions'::regclass, 'investigation_events'::regclass)",
        )
        orphan_executions = _scalar(
            conn,
            "SELECT count(*) FROM red_team_executions e"
            " LEFT JOIN red_team_runs r USING (run_id) WHERE r.run_id IS NULL",
        )
        orphan_events = _scalar(
            conn,
            "SELECT count(*) FROM investigation_events e"
            " LEFT JOIN investigations i USING (investigation_id) WHERE i.investigation_id IS NULL",
        )
        checks.append(
            Check(
                "foreign keys exist and no execution or event is orphaned",
                fks == 2 and orphan_executions == 0 and orphan_events == 0,
                f"{fks} foreign keys, {orphan_executions} orphan executions, "
                f"{orphan_events} orphan events",
            )
        )
        responses = _scalar(
            conn,
            "SELECT count(*) FROM stream_archive WHERE topic = 'rag-responses'",
        )
        unmatched_flash = _scalar(
            conn,
            "SELECT count(*) FROM stream_archive j WHERE j.topic = 'judge-verdicts' AND NOT EXISTS"
            " (SELECT 1 FROM stream_archive r WHERE r.topic = 'rag-responses'"
            "  AND r.value->>'event_id' = j.value->>'source_event_id')",
        )
        unmatched_frontier = _scalar(
            conn,
            "SELECT count(*) FROM stream_archive f WHERE f.topic = 'rag-frontier-verdicts'"
            " AND NOT EXISTS (SELECT 1 FROM stream_archive r WHERE r.topic = 'rag-responses'"
            "  AND r.value->>'app_trace_id' = f.value->>'app_trace_id')",
        )
        checks.append(
            Check(
                "every flash and frontier verdict has its request in the archive",
                unmatched_flash == 0 and unmatched_frontier == 0,
                f"{responses} requests; {unmatched_flash} flash and {unmatched_frontier} "
                "frontier verdicts without one",
            )
        )
    again = materialize(directory, url)
    checks.append(
        Check("a second restore adds nothing", all(v == 0 for v in again.values()), str(again))
    )
    with psycopg.connect(url, autocommit=True) as conn:
        victim = conn.execute(
            "SELECT execution_id FROM red_team_executions ORDER BY execution_id LIMIT 1"
        ).fetchone()
        assert victim is not None
        conn.execute(
            "UPDATE red_team_executions SET reason = 'edited during recovery'"
            " WHERE execution_id = %s",
            victim,
        )
    materialize(directory, url)
    with psycopg.connect(url) as conn:
        kept = _scalar(
            conn,
            "SELECT count(*) FROM red_team_executions"
            " WHERE execution_id = %s AND reason = 'edited during recovery'",
            victim[0],
        )
    checks.append(Check("a restore never overwrites an existing row", kept == 1, str(victim[0])))
    return checks


def _statements(sql: str) -> list[str]:
    no_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", "", no_block)
    return [p.strip() for p in no_line.split(";") if p.strip()]


def _replay_topic(token: str, topic: str) -> str:
    return f"recovery-{token}-{topic}"


@asynccontextmanager
async def _risingwave_database(name: str, token: str, bootstrap: str) -> Any:
    """A disposable RisingWave database and the three replay topics, removed on exit."""
    from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]

    from finsentry.risingwave.dao import risingwave_dsn

    admin_dsn = risingwave_dsn()
    own_dsn = re.sub(r"/[^/?]+$", f"/{name}", admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {_checked_name(name)}")  # noqa: S608
    try:
        yield own_dsn
    finally:
        with psycopg.connect(own_dsn, autocommit=True) as conn:
            for view in conn.execute(
                "SELECT name FROM rw_catalog.rw_materialized_views WHERE schema_id ="
                " (SELECT id FROM rw_catalog.rw_schemas WHERE name = 'public')"
            ).fetchall():
                conn.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view[0]} CASCADE")
            for source in SOURCES.values():
                conn.execute(f"DROP SOURCE IF EXISTS {source} CASCADE")
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {_checked_name(name)}")
        admin: Any = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
        await admin.start()
        try:
            await admin.delete_topics([_replay_topic(token, t) for t in TOPICS])
        except Exception:  # noqa: BLE001 - a topic that never got created has nothing to delete
            pass
        finally:
            await admin.close()


async def _wait_for(probe: Callable[[], int], want: int, seconds: float = 90.0) -> int:
    deadline = time.monotonic() + seconds
    got = probe()
    while got < want and time.monotonic() < deadline:
        await asyncio.sleep(1.0)
        got = probe()
    return got


async def stream_checks(directory: Path, bootstrap: str, token: str) -> list[Check]:
    """Rebuild the RisingWave sources and views from the archive into a disposable database
    and read traces back through the dashboard's own trace routes."""
    expected = _expected(directory)
    name = _checked_name(f"{PREFIX}{token}")
    checks: list[Check] = []
    async with _risingwave_database(name, token, bootstrap) as own_dsn:
        # A source needs its topic to exist, so the replay comes first. The sources then read
        # it from the earliest offset.
        for topic in TOPICS:
            await republish(directory, topic, _replay_topic(token, topic), bootstrap)
        sql = INIT_SQL.read_text("utf-8")
        for topic in TOPICS:
            sql = sql.replace(f"'{topic}'", f"'{_replay_topic(token, topic)}'")
        with psycopg.connect(own_dsn, autocommit=True) as conn:
            for statement in _statements(sql):
                conn.execute(statement)
            views = _scalar(
                conn,
                "SELECT count(*) FROM rw_catalog.rw_materialized_views WHERE schema_id ="
                " (SELECT id FROM rw_catalog.rw_schemas WHERE name = 'public')",
            )
        checks.append(Check("init.sql rebuilds the derived views", views == 8, f"{views} views"))
        with psycopg.connect(own_dsn, autocommit=True) as conn:
            for topic, source in SOURCES.items():
                got = await _wait_for(
                    lambda s=source: _scalar(conn, f"SELECT count(*) FROM {s}"),  # type: ignore[misc]  # noqa: S608
                    expected[topic],
                )
                checks.append(
                    Check(
                        f"{source} holds every archived {topic} record",
                        got == expected[topic],
                        f"{got} of {expected[topic]}",
                    )
                )
            buckets = _scalar(
                conn, "SELECT coalesce(sum(total_requests), 0) FROM mv_request_throughput_1m"
            )
        checks.append(
            Check(
                "the request view counts every archived request",
                buckets == expected["rag-responses"],
                f"{buckets} of {expected['rag-responses']}",
            )
        )
        checks += await _render_traces(directory, own_dsn)
    return checks


async def _render_traces(directory: Path, own_dsn: str) -> list[Check]:
    """Open archived traces through the dashboard's own trace routes, reading the disposable
    database, and compare what comes back with what the archive holds."""
    from finsentry.dashboard.app import app as dashboard
    from finsentry.mcp.state import dao

    name = "the dashboard renders archived traces from the restored views"
    values: list[dict[str, Any]] = [
        r["value"]  # type: ignore[misc]
        for r in read_lines(directory / "stream" / "rag-responses.jsonl")
    ]
    archived = [v for v in values if v["status"] == "success" and v["citations"]]
    blocked = [v for v in values if v["status"] == "blocked"]
    if not archived or not blocked:
        return [Check(name, False, "the archive has no delivered or no blocked request")]
    previous = os.environ.get("RISINGWAVE_DB")
    os.environ["RISINGWAVE_DB"] = own_dsn.rsplit("/", 1)[1]
    try:
        await dao.open()
        if not dao.connected:
            return [Check(name, False, "no connection to the disposable RisingWave database")]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dashboard), base_url="http://t"
        ) as client:
            listed = (await client.get("/traces?limit=50")).json()["traces"]
            delivered = (await client.get(f"/traces/{archived[0]['app_trace_id']}")).json()
            refused = (await client.get(f"/traces/{blocked[0]['app_trace_id']}")).json()
        same_answer = delivered["found"] and delivered["answer"] == archived[0]["answer"]
        same_citations = len(delivered["citations"]) == len(archived[0]["citations"])
        same_block = refused["found"] and refused["block_rail"] == blocked[0]["block_rail"]
        return [
            Check(
                name,
                bool(listed and same_answer and same_citations and same_block),
                f"{len(listed)} listed; a delivered trace returns its archived answer and "
                f"{len(delivered['citations'])} citations; a blocked trace returns its "
                f"{refused['block_rail']} block",
            )
        ]
    finally:
        await dao.close()
        if previous is None:
            os.environ.pop("RISINGWAVE_DB", None)
        else:
            os.environ["RISINGWAVE_DB"] = previous


async def render_checks(directory: Path, url: str) -> list[Check]:
    """Read the restored Red Team and Agent records through the application's own routers,
    with a planner and a tool session that fail the check if anything asks them for work."""
    from finsentry.investigator.api import build_router as build_investigations
    from finsentry.investigator.service import InvestigationDeps
    from finsentry.redteam.api import build_router as build_red_team
    from finsentry.redteam.deps import Deps

    expected = _expected(directory)
    model_calls: list[str] = []

    def planner_factory() -> Any:
        model_calls.append("planner built")
        raise RuntimeError("a read must not build a planner")

    @asynccontextmanager
    async def tools() -> Any:
        model_calls.append("tool session opened")
        raise RuntimeError("a read must not open the tool server")
        yield  # pragma: no cover

    app = FastAPI()
    app.include_router(
        build_red_team(
            lambda: Deps(
                app=app,
                database_url=url,
                input_adapter=None,
                retrieval_rail=None,
                schema_rail=None,
                phrase_rail=None,
                faithfulness_rail=None,
                metrics_client=None,
            )
        )
    )
    deps = InvestigationDeps(database_url=url, planner_factory=planner_factory, tool_session=tools)
    app.include_router(build_investigations(lambda: deps))
    checks: list[Check] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        runs = (await c.get("/ops/redteam/runs?limit=50")).json()
        executions: list[dict[str, Any]] = []
        offset: int | None = 0
        while offset is not None:
            page = (await c.get(f"/ops/redteam/executions?limit=100&offset={offset}")).json()
            executions += page["executions"]
            offset = page["next_offset"]
        with_evidence = [e for e in executions if e["evidence"]]
        checks.append(
            Check(
                "the Red Team console reads every restored run and execution",
                len(runs) == expected["red_team_runs"]
                and len(executions) == expected["red_team_executions"],
                f"{len(runs)} runs, {len(executions)} executions, "
                f"{len(with_evidence)} with an evidence payload",
            )
        )
        listed = (await c.get("/ops/investigations?limit=50")).json()["investigations"]
        events = 0
        complete = 0
        for item in listed:
            detail = (await c.get(f"/ops/investigations/{item['investigation_id']}")).json()
            events += len(detail["timeline"])
            complete += int(detail["report"] is not None or detail["status"] != "completed")
        checks.append(
            Check(
                "the Agent reads every restored investigation with its timeline",
                len(listed) == expected["investigations"]
                and events == expected["investigation_events"],
                f"{len(listed)} investigations, {events} timeline events",
            )
        )
    checks.append(Check("reading made no planner or tool call", not model_calls, str(model_calls)))
    return checks


async def create_and_drop(
    admin_url: str, work: Callable[[str], Awaitable[list[Check]]]
) -> list[Check]:
    """Run `work` against a fresh disposable Postgres database and always drop it."""
    name = _checked_name(f"{PREFIX}{secrets.token_hex(4)}")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name} TEMPLATE template0")  # noqa: S608
    try:
        return await work(_database_url(admin_url, name))
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")  # noqa: S608


async def recover(directory: Path, admin_url: str, bootstrap: str) -> list[Check]:
    """The whole rehearsal. Postgres first, then the stream views, then the application reads."""
    token = secrets.token_hex(4)
    # The maintenance database, so the development database is not even connected to.
    admin_url = _database_url(admin_url, "postgres")

    async def work(url: str) -> list[Check]:
        checks = postgres_checks(directory, url)
        checks += await render_checks(directory, url)
        checks += await stream_checks(directory, bootstrap, token)
        return checks

    return await create_and_drop(admin_url, work)
