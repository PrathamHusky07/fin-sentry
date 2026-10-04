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
