"""Tests for scripts/init_risingwave.py: _split_statements and _ensure_topics."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package; import via sys.path manipulation.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from init_risingwave import _ensure_topics, _split_statements  # noqa: E402, I001


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


def _make_completed(returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


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
    already_exists = _make_completed(returncode=1, stderr="TOPIC_ALREADY_EXISTS: rag-responses")
    with patch("subprocess.run", return_value=already_exists):
        # Must not raise
        _ensure_topics(["rag-responses"])


def test_ensure_topics_raises_on_unexpected_error() -> None:
    failure = _make_completed(returncode=1, stderr="connection refused")
    with patch("subprocess.run", return_value=failure):
        with pytest.raises(RuntimeError, match="Failed to ensure topic"):
            _ensure_topics(["rag-responses"])
