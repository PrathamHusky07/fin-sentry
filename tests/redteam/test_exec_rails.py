"""Input-rail and retrieval-rail executors, with the adapter and rail replaced by fakes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nemoguardrails.rails.llm.options import RailStatus

from finsentry.rails.retrieval.rail import ChunkDrop, RetrievalReport
from finsentry.redteam import exec_rails
from finsentry.redteam.classify import classify
from finsentry.redteam.deps import ScenarioSetupError
from tests.redteam.helpers import make_deps, scenario


def _adapter(status: Any, content: str, rail: str | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.run = AsyncMock(
        return_value=([{"role": "user", "content": content}], status, rail, None)
    )
    return adapter


async def _pii(adapter: MagicMock | None):  # type: ignore[no-untyped-def]
    s = scenario("PII-001")
    obs = await exec_rails.run_input_rails(s, make_deps(input_adapter=adapter))  # type: ignore[arg-type]
    return obs, classify(s, obs)


async def test_pii_redaction_of_every_expected_entity_is_caught_by_pii_redaction() -> None:
    content = "SSN <REDACTED_US_SSN> email <REDACTED_EMAIL_ADDRESS> summarize."
    obs, result = await _pii(_adapter(RailStatus.MODIFIED, content))
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_layer == "pii-redaction"
    assert obs.evidence["redacted_entities"] == ["EMAIL_ADDRESS", "US_SSN"]


async def test_a_partial_redaction_is_a_miss_and_names_the_leaked_entity() -> None:
    obs, result = await _pii(
        _adapter(RailStatus.MODIFIED, "email <REDACTED_EMAIL_ADDRESS> and 219-09-9999")
    )
    assert result.outcome == "missed"
    assert obs.evidence["leaked_entities"] == ["US_SSN"]
    assert result.acting_layer is None


async def test_text_that_passes_unchanged_is_a_miss() -> None:
    _, result = await _pii(_adapter(RailStatus.PASSED, "My SSN is 219-09-9999"))
    assert result.outcome == "missed"


async def test_a_block_by_another_rail_is_caught_by_that_rail_and_flagged() -> None:
    obs, result = await _pii(_adapter(RailStatus.BLOCKED, "x", rail="check hazard taxonomy"))
    assert (result.outcome, result.expectation) == ("caught", "not_met")
    assert result.acting_layer == "llama-guard-3"
    assert obs.evidence["rail_reported"] == "check hazard taxonomy"
    assert "before redaction could be observed" in result.reason


async def test_a_block_from_an_unrecognized_rail_is_inconclusive_not_caught() -> None:
    _, result = await _pii(_adapter(RailStatus.BLOCKED, "x", rail="some new flow"))
    assert result.outcome == "inconclusive"
    assert result.acting_layer is None


async def test_an_input_stack_failure_is_evaluator_unavailable() -> None:
    adapter = MagicMock()
    adapter.run = AsyncMock(side_effect=RuntimeError("engine down"))
    obs, result = await _pii(adapter)
    assert result.outcome == "evaluator_unavailable"
    assert "engine down" not in result.reason
    assert obs.defense_acted is False


async def test_a_missing_input_stack_is_evaluator_unavailable() -> None:
    _, result = await _pii(None)
    assert result.outcome == "evaluator_unavailable"


def _chunks(*roles: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(chunk_id=f"c{i}", role=r) for i, r in enumerate(roles)]


async def _retrieval(
    scenario_id: str, report: RetrievalReport | Exception, roles=("attack", "control")
):  # type: ignore[no-untyped-def]
    s = scenario(scenario_id)
    rail = MagicMock()
    if isinstance(report, Exception):
        rail.check_chunks_reported.side_effect = report
    else:
        rail.check_chunks_reported.return_value = report
    with patch.object(exec_rails, "_borrow_rows", return_value=_chunks(*roles)):
        obs = await exec_rails.run_retrieval_rail(s, make_deps(retrieval_rail=rail))
    return obs, classify(s, obs)


def _report(drop_check: str | None, kept: list[str]) -> RetrievalReport:
    drops = [ChunkDrop("c0", drop_check, "detail", 0.97)] if drop_check else []  # type: ignore[arg-type]
    return RetrievalReport(kept=[SimpleNamespace(chunk_id=i) for i in kept], drops=drops)


async def test_a_dropped_attack_chunk_with_the_control_kept_is_caught_by_the_named_check() -> None:
    obs, result = await _retrieval("IND-001", _report("prompt-guard", ["c1"]))
    assert (result.outcome, result.expectation) == ("caught", "met")
    assert result.acting_check == "prompt-guard"
    assert obs.evidence["control_kept"] is True


async def test_the_wrong_check_dropping_the_chunk_does_not_meet_the_expectation() -> None:
    _, result = await _retrieval("IND-001", _report("source-trust", ["c1"]))
    assert (result.outcome, result.expectation) == ("caught", "not_met")


async def test_a_surviving_attack_chunk_is_a_miss() -> None:
    _, result = await _retrieval("IND-001", _report(None, ["c0", "c1"]))
    assert result.outcome == "missed"


async def test_dropping_the_control_too_is_inconclusive_not_a_catch() -> None:
    _, result = await _retrieval("IND-001", _report("prompt-guard", []))
    assert result.outcome == "inconclusive"
    assert "control" in result.reason


async def test_a_retrieval_rail_error_is_evaluator_unavailable() -> None:
    _, result = await _retrieval("IND-001", RuntimeError("model gone"))
    assert result.outcome == "evaluator_unavailable"


async def test_ind002_expects_the_source_trust_check() -> None:
    _, result = await _retrieval("IND-002", _report("source-trust", ["c1"]))
    assert (result.outcome, result.expectation) == ("caught", "met")


async def test_an_unbuildable_chunk_raises_a_setup_error_not_a_verdict() -> None:
    s = scenario("IND-001")
    with (
        patch.object(exec_rails, "_borrow_rows", side_effect=ScenarioSetupError("no corpus chunk")),
        pytest.raises(ScenarioSetupError),
    ):
        await exec_rails.run_retrieval_rail(s, make_deps(retrieval_rail=MagicMock()))
