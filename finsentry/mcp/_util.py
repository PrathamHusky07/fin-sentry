"""Small helpers shared by the MCP tool domain modules."""

from __future__ import annotations

import datetime
from typing import Any


def iso(value: Any) -> str | None:
    """Convert a psycopg-returned TIMESTAMPTZ (datetime) to an ISO-8601
    string, passing None through. MCP structured output must be JSON-safe;
    RisingWave/psycopg returns timestamptz columns as datetime objects."""
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


MAX_LIMIT = 500
"""Ceiling for a caller-supplied `limit` on an investigation tool. These
tools exist for incident drill-down (recent failures, recent injection
attempts), not bulk export, and `limit` gets inlined as a SQL literal
(RisingWave's streaming planner rejects a bound LIMIT parameter -- see
finsentry/mcp/tools/traces.py), so it is validated before that happens."""


def validate_limit(limit: int, max_limit: int = MAX_LIMIT) -> None:
    """Reject a `limit` outside [1, max_limit]. Raises ValueError, which the
    MCP SDK surfaces to the caller as a CallToolResult(is_error=True)."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    if limit > max_limit:
        raise ValueError(f"limit must be <= {max_limit}, got {limit}")
