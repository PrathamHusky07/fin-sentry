"""Replay a recorded live run's plans through the current loop, at no model cost.

A scorecard written with --live keeps every plan the model returned, per case. Replaying them
runs the same model output through whatever the loop is now, so a change to the ledger or the
review can be compared with the live result without another model call. It tests the loop on
fixed model output. It does not test the model, and a replayed run is never a live result.
"""

from __future__ import annotations

import json
from pathlib import Path

from finsentry.investigator.planning import Plan, PlanningError


class ReplayPlanner:
    cost_usd = 0.0

    def __init__(self, recorded: Path) -> None:
        data = json.loads(recorded.read_text())
        self.name = f"replay of {data['label']}"
        self.current = ""
        self._queues = {
            f"inc-{c['case_id']}": list(c.get("planner_transcript", [])) for c in data["cases"]
        }

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        queue = self._queues.get(self.current, [])
        if not queue:
            raise PlanningError("the recording has no further plan for this case")
        item = queue.pop(0)
        if "error" in item:
            raise PlanningError(item["error"])
        return Plan.model_validate(item["plan"])
