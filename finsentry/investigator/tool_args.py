"""
Argument validation for the nine read-only tools, run before any call is made.

The server hides the message of an exception a tool raises: a ValueError for limit 0 and a
backend failure both reach the client as "Error executing tool". A client therefore cannot
learn from the reply whether it sent a bad argument or the source was down. This module
decides that before the call, from the tools' own signatures and the limits the server
enforces (imported from the tool modules, so they cannot drift). A call that passes here and
still fails on the server is a source failure, never a caller error.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Mapping
from functools import cache
from typing import get_type_hints

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from finsentry.investigator.contracts import TOOL_NAMES
from finsentry.investigator.tool_contract import McpReadTools
from finsentry.mcp._util import MAX_LIMIT
from finsentry.mcp.tools.redteam import MAX_EXECUTION_PAGE
from finsentry.mcp.tools.trace_evidence import MAX_TRACE_PAGE

MAX_LIMITS: dict[str, int] = {
    "get_failing_traces": MAX_LIMIT,
    "search_prompt_injections": MAX_LIMIT,
    "search_traces": MAX_TRACE_PAGE,
    "list_red_team_executions": MAX_EXECUTION_PAGE,
}
MAX_SCENARIO_ID_CHARS = 16
UUID_ARGS = ("run_id", "execution_id")


@cache
def _args_model(tool: str) -> type[BaseModel]:
    method = getattr(McpReadTools, tool)
    hints = get_type_hints(method)
    fields = {
        name: (hints[name], ... if p.default is inspect.Parameter.empty else p.default)
        for name, p in inspect.signature(method).parameters.items()
        if name != "self"
    }
    model: type[BaseModel] = create_model(  # type: ignore[call-overload]
        f"{tool}_args", __config__=ConfigDict(extra="forbid"), **fields
    )
    return model


def validate_tool_args(tool: str, args: Mapping[str, object]) -> list[str]:
    """Why these arguments would be rejected, or an empty list when the call is well formed."""
    if tool not in TOOL_NAMES:
        return [f"{tool} is not one of the nine read-only tools"]
    try:
        parsed = _args_model(tool).model_validate(args).model_dump()
    except ValidationError as exc:
        return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
    problems: list[str] = []
    limit = parsed.get("limit")
    if limit is not None and not 1 <= limit <= MAX_LIMITS.get(tool, MAX_LIMIT):
        problems.append(f"limit must be between 1 and {MAX_LIMITS.get(tool, MAX_LIMIT)}")
    if parsed.get("offset", 0) < 0:
        problems.append("offset must be >= 0")
    scenario_id = parsed.get("scenario_id")
    if scenario_id is not None and len(scenario_id) > MAX_SCENARIO_ID_CHARS:
        problems.append(f"scenario_id must be at most {MAX_SCENARIO_ID_CHARS} characters")
    for name in UUID_ARGS:
        value = parsed.get(name)
        if value is not None:
            try:
                uuid.UUID(value)
            except ValueError:
                problems.append(f"{name} must be a UUID")
    return problems
