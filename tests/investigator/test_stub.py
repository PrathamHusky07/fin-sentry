"""The always-abstain stub exercises the loop mechanics and nothing else."""

from __future__ import annotations

from typing import Any

from finsentry.investigator.adapter import ReadOnlyAdapter
from finsentry.investigator.citations import validate_report
from finsentry.investigator.contracts import IncidentTrigger, TimeWindow
from finsentry.investigator.fixtures import ANCHOR, at
from finsentry.investigator.loop import start_investigation
from finsentry.investigator.stub import AlwaysAbstainInvestigator


class _NoTools:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the stub must not call {name}")


async def test_the_stub_abstains_without_touching_a_tool_or_a_model() -> None:
    state = start_investigation(
        "inc-1",
        IncidentTrigger(kind="faithfulness_block_cluster", description="blocks rose"),
        TimeWindow(start=at(60), end=ANCHOR),
    )
    adapter = ReadOnlyAdapter(_NoTools())  # type: ignore[arg-type]
    result = await AlwaysAbstainInvestigator().investigate(state, adapter, lambda: 0.0)

    assert result.report.outcome == "abstention"
    assert result.state.status == "stopped"
    assert result.state.stopping_reason == "justified_abstention"
    assert result.state.usage.tool_calls == 0 and result.state.usage.inference_calls == 0
    assert result.report.ranked_hypotheses == [] and result.report.causal_claims == []
    assert validate_report(result.report, result.state).valid


async def test_a_started_investigation_declares_the_tools_known_gaps() -> None:
    state = start_investigation(
        "inc-1",
        IncidentTrigger(kind="drift_degradation", description="kappa fell"),
        TimeWindow(start=at(60), end=ANCHOR),
    )
    kinds = {g.kind for g in state.known_data_gaps}
    assert {"not_persisted", "withheld", "snapshot_only", "ambiguous"} <= kinds
