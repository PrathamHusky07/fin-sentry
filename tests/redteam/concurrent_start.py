"""
One independent runner process for the cross-process single-active-run test.

Run as `python -m tests.redteam.concurrent_start <start_at_epoch> <force_race>`. It is a
separate interpreter with its own asyncio.Lock, so two copies share nothing but the
Postgres database, which is the situation of two gateway replicas. It waits for the
shared start time, calls the real runner.start_run, and prints one JSON line.

With force_race=1 the first "is a run active" check is made to see no run, so both
processes pass the check and race to create. That is the interleaving the in-process
lock cannot prevent. Nothing about the database mechanism is replaced.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from finsentry.redteam import runner, store
from finsentry.redteam.classify import Observation
from finsentry.redteam.records import RunRequest
from tests.redteam.helpers import make_deps


async def _hold_open(*_: object, **__: object) -> Observation:
    # Keep the winner's run in the running state long enough for the other process
    # to try, then let it finish so the test leaves nothing running.
    await asyncio.sleep(2.0)
    return Observation(summary="x", evidence={"gateway_status": 200}, attack_passed=True)


async def main(start_at: float, force_race: bool) -> None:
    runner._execute = _hold_open  # type: ignore[assignment]
    if force_race:
        real = store.active_run_id
        calls = {"n": 0}

        def blind_first_check(url: str) -> str | None:
            calls["n"] += 1
            return None if calls["n"] == 1 else real(url)

        store.active_run_id = blind_first_check  # type: ignore[assignment]
    while time.time() < start_at:
        await asyncio.sleep(0.001)
    try:
        run_id = await runner.start_run(RunRequest(scenario_ids=["DI-001"]), make_deps())
        print(json.dumps({"started": run_id}), flush=True)
    except runner.RunRejectedError as exc:
        print(json.dumps({"rejected": exc.status, "run_id": exc.run_id}), flush=True)
    if runner._tasks:
        await asyncio.gather(*runner._tasks)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]), sys.argv[2] == "1"))
