#!/usr/bin/env python3
"""Day 7 Phase 5A: a real investigation arc through the MCP server's five
backed tools, against actual persisted platform state. Zero Gemini calls --
every tool here only reads already-persisted RisingWave rows or reliability
artifacts.

Arc: get_failing_traces -> pick a trace -> explain_guardrail_decision ->
get_judge_scores -> get_drift_report -> search_prompt_injections.

Requires RisingWave reachable (RISINGWAVE_HOST/PORT/USER/DB env vars, same as
the dashboard) with at least one real failing trace already in rag_events --
this does not synthesize one. Run with:
    python scripts/mcp_investigation_demo_d7.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finsentry.mcp.server import server
from finsentry.mcp.state import dao

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs/measurements/mcp/mcp-investigation-demo-d7.json"
)


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await server.call_tool(name, arguments)
    return {
        "tool": name,
        "arguments": arguments,
        "is_error": result.is_error,
        "structured_content": result.structured_content,
    }


async def _run() -> None:
    await dao.open()
    print(f"RisingWave connected: {dao.connected}")

    arc: list[dict[str, Any]] = []

    failing = await _call("get_failing_traces", {"time_window_minutes": 1440, "limit": 10})
    arc.append(failing)
    traces = failing["structured_content"]["traces"]
    print(f"get_failing_traces: {len(traces)} traces")

    if not traces:
        print("No failing traces found in the last 24h -- cannot complete the drill-down arc.")
        print("Reporting the partial arc (get_failing_traces + get_drift_report only).")
        drift = await _call("get_drift_report", {})
        arc.append(drift)
        _save(arc)
        await dao.close()
        return

    picked_trace_id = traces[0]["app_trace_id"]
    print(f"Picked trace: {picked_trace_id}")

    explain = await _call("explain_guardrail_decision", {"app_trace_id": picked_trace_id})
    arc.append(explain)
    print(f"explain_guardrail_decision: found={explain['structured_content']['found']}")

    judge_scores = await _call("get_judge_scores", {"app_trace_id": picked_trace_id})
    arc.append(judge_scores)
    print(f"get_judge_scores: {judge_scores['structured_content']['count']} verdicts")

    drift = await _call("get_drift_report", {})
    arc.append(drift)
    reading = drift["structured_content"]["last_health_reading"]
    print(f"get_drift_report: state={reading['state'] if reading else None}")

    injections = await _call(
        "search_prompt_injections", {"time_window_minutes": 1440, "limit": 20}
    )
    arc.append(injections)
    print(f"search_prompt_injections: {len(injections['structured_content']['direct'])} direct")

    _save(arc)
    await dao.close()


def _save(arc: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(arc, indent=2, sort_keys=True, default=str))
    print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(_run())
