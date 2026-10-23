"""Tests for scripts/init_risingwave.py: _split_statements, _ensure_topics and the no-drop guard."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package; import via sys.path manipulation.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from init_risingwave import (  # noqa: E402, I001
    _JUDGE_VERDICTS_TOPIC,
    _RAG_RESPONSES_TOPIC,
    _SQL_PATH,
    _TEARDOWN_PATH,
    _ensure_topics,
    _split_statements,
    main,
    plan_statements,
)


# ---------------------------------------------------------------------------
# _split_statements
# ---------------------------------------------------------------------------


def test_split_statements_splits_two_simple_statements() -> None:
    sql = "CREATE TABLE a (x INT);\nCREATE TABLE b (y INT);"
    result = _split_statements(sql)
    assert len(result) == 2
    assert "CREATE TABLE a" in result[0]
    assert "CREATE TABLE b" in result[1]


def test_split_statements_handles_semicolon_in_line_comment() -> None:
    sql = "-- foo; bar\nCREATE TABLE t(x INT);\nCREATE TABLE u(y INT);"
    result = _split_statements(sql)
    assert len(result) == 2
    assert "CREATE TABLE t" in result[0]
    assert "CREATE TABLE u" in result[1]


def test_split_statements_handles_block_comment_with_semicolons() -> None:
    sql = "/* a; b; c */ CREATE TABLE t(x INT);"
    result = _split_statements(sql)
    assert len(result) == 1
    assert "CREATE TABLE t" in result[0]


def test_split_statements_drops_pure_comment_chunks() -> None:
    sql = "-- only a comment\n-- another comment\n"
    result = _split_statements(sql)
    assert result == []


def test_split_statements_preserves_multi_line_ddl() -> None:
    sql = "\n".join([
        "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_test AS",
        "SELECT",
        "    window_start,",
        "    window_end,",
        "    COUNT(*) AS total_requests,",
        "    AVG(total_latency_ms) AS avg_latency_ms,",
        "    SUM(input_tokens) AS tokens,",
        "    MAX(cost_usd) AS max_cost,",
        "    MIN(cost_usd) AS min_cost",
        "FROM TUMBLE(rag_events, timestamp_utc, INTERVAL '1 minute')",
        "GROUP BY window_start, window_end;",
    ])
    result = _split_statements(sql)
    assert len(result) == 1
    assert "CREATE MATERIALIZED VIEW" in result[0]
    assert "GROUP BY window_start, window_end" in result[0]


# ---------------------------------------------------------------------------
# _ensure_topics
# ---------------------------------------------------------------------------


def _make_completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_ensure_topics_calls_rpk_for_each_topic() -> None:
    with patch("subprocess.run", return_value=_make_completed(0)) as mock_run:
        _ensure_topics(["rag-responses", "judge-verdicts"])

    assert mock_run.call_count == 2
    first_call_args = mock_run.call_args_list[0][0][0]
    second_call_args = mock_run.call_args_list[1][0][0]
    assert first_call_args == [
        "docker", "exec", "finsentry-redpanda", "rpk", "topic", "create", "rag-responses"
    ]
    assert second_call_args == [
        "docker", "exec", "finsentry-redpanda", "rpk", "topic", "create", "judge-verdicts"
    ]


def test_ensure_topics_treats_topic_already_exists_as_success() -> None:
    # rpk writes the marker to stdout and exits 1 (empirically verified)
    already_exists = _make_completed(
        returncode=1,
        stdout="TOPIC_ALREADY_EXISTS: The topic has already been created",
        stderr="",
    )
    with patch("subprocess.run", return_value=already_exists):
        # Must not raise
        _ensure_topics(["rag-responses"])


def test_ensure_topics_raises_on_unexpected_error() -> None:
    failure = _make_completed(returncode=1, stdout="", stderr="some real failure")
    with patch("subprocess.run", return_value=failure):
        with pytest.raises(RuntimeError, match="exit=1") as exc_info:
            _ensure_topics(["rag-responses"])
    msg = str(exc_info.value)
    assert "stdout=''" in msg
    assert "stderr='some real failure'" in msg


# ---------------------------------------------------------------------------
# Contract test: script constants must match finsentry.events.topics
# ---------------------------------------------------------------------------


def test_script_topic_constants_match_events_module() -> None:
    """Contract: the script's local topic constants must match the canonical
    Python definitions in finsentry.events.topics. If either side is renamed
    without updating the other, the pipeline will silently break."""
    from finsentry.events.topics import JUDGE_VERDICTS_TOPIC, RAG_RESPONSES_TOPIC

    assert _RAG_RESPONSES_TOPIC == RAG_RESPONSES_TOPIC
    assert _JUDGE_VERDICTS_TOPIC == JUDGE_VERDICTS_TOPIC


# ---------------------------------------------------------------------------
# History guard: a routine init must never drop a view or its stored rows
# ---------------------------------------------------------------------------
#
# The topics expire old events, so the stored rows of each materialized view can be the only
# copy of that history. These tests read the real init.sql and teardown.sql and run main()
# against a recording connection, so nothing here touches a RisingWave database.

_DESTRUCTIVE = re.compile(r"^\s*(DROP|TRUNCATE|DELETE|ALTER)\b", re.IGNORECASE)
_VIEW_NAME = re.compile(r"MATERIALIZED VIEW\s+(?:IF (?:NOT )?EXISTS\s+)?(\w+)", re.IGNORECASE)


def test_default_plan_contains_no_destructive_statement() -> None:
    destructive = [s for s in plan_statements() if _DESTRUCTIVE.match(s)]
    assert destructive == []


def test_init_sql_alone_contains_no_destructive_statement() -> None:
    statements = _split_statements(_SQL_PATH.read_text())
    assert statements, "init.sql produced no statements"
    assert [s for s in statements if _DESTRUCTIVE.match(s)] == []


def test_init_sql_creates_every_object_only_if_missing() -> None:
    creates = [
        s for s in _split_statements(_SQL_PATH.read_text()) if s.upper().startswith("CREATE")
    ]
    assert len(creates) == 12  # three sources and nine views
    assert all("IF NOT EXISTS" in s.split("(")[0].split(" AS")[0].upper() for s in creates)


def test_default_plan_keeps_the_history_view_and_the_exact_latency_view() -> None:
    plan = "\n".join(plan_statements())
    assert "mv_request_throughput_1m" in plan
    assert "mv_request_latency_exact_1m" in plan
    assert "DROP" not in plan.upper()


def test_destroy_plan_drops_exactly_the_views_init_creates_and_drops_first() -> None:
    plan = plan_statements(destroy_history=True)
    drops = [s for s in plan if _DESTRUCTIVE.match(s)]
    created = {
        m.group(1)
        for s in plan_statements()
        if s.upper().startswith("CREATE MATERIALIZED VIEW")
        for m in [_VIEW_NAME.search(s)]
        if m
    }
    dropped = {m.group(1) for s in drops for m in [_VIEW_NAME.search(s)] if m}
    assert dropped == created
    assert len(created) == 9
    assert plan[: len(drops)] == drops


def test_teardown_file_is_only_reachable_through_the_explicit_flag() -> None:
    assert _TEARDOWN_PATH.read_text() not in _SQL_PATH.read_text()
    assert plan_statements() == _split_statements(_SQL_PATH.read_text())


class _RecordingCursor:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self._log.append(statement)


class _RecordingConnection:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self._log)

    def close(self) -> None:
        return None


def _run_main(argv: list[str]) -> list[str]:
    log: list[str] = []
    with (
        patch("init_risingwave._ensure_topics"),
        patch("psycopg.connect", return_value=_RecordingConnection(log)),
    ):
        assert main(argv) == 0
    return log


def test_default_run_sends_no_drop_to_the_database() -> None:
    executed = _run_main([])
    assert len(executed) == 12
    assert [s for s in executed if _DESTRUCTIVE.match(s)] == []


def test_destroy_flag_is_the_only_way_a_run_sends_drops() -> None:
    executed = _run_main(["--destroy-history-and-rebuild"])
    assert len([s for s in executed if _DESTRUCTIVE.match(s)]) == 9
    assert len(executed) == 21


def test_dry_run_prints_no_drop_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run"]) == 0
    assert "DROP" not in capsys.readouterr().out.upper()
