from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.prompts.rubric_v2_faithjudge import PROMPT_VERSION
from finsentry.rails.output.cost_governance import CostBudget
from finsentry.reliability import canary
from finsentry.reliability.canary import BenchmarkCanaryScorer, select_canary_ids
from finsentry.reliability.controller import DriftController
from finsentry.reliability.health import DriftConfig

_ROWS: list[dict[str, Any]] = [
    {"id": "r0", "question": "q0", "context": "c0", "response": "a0", "is_hallucination": True},
    {"id": "r1", "question": "q1", "context": "c1", "response": "a1", "is_hallucination": False},
    {"id": "r2", "question": "q2", "context": "c2", "response": "a2", "is_hallucination": True},
    {"id": "r3", "question": "q3", "context": "c3", "response": "a3", "is_hallucination": False},
    {"id": "r4", "question": "q4", "context": "c4", "response": "a4", "is_hallucination": False},
]
_M4_IDS = {"r0", "r1"}  # 2 of the 5 rows are "already M4-scored" -> eligible pool = {r2, r3, r4}


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    part = MagicMock()
    part.text = text
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response.candidates = [candidate]
    usage = MagicMock()
    usage.prompt_token_count = 100
    usage.candidates_token_count = 20
    usage.thoughts_token_count = 0
    response.usage_metadata = usage
    return response


def _rubric_response(score: float) -> str:
    return json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "faithfulness_score": score,
            "rubric_reasoning": "r",
            "cited_chunks_supporting": [],
            "cited_chunks_contradicting": [],
        }
    )


def _adapter_and_budget(
    side_effect: object, cost_budget: CostBudget | None = None
) -> tuple[GeminiRubricAdapter, CostBudget]:
    budget = cost_budget or CostBudget()
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effect
    with patch("google.genai.Client", return_value=mock_client):
        adapter = GeminiRubricAdapter(cost_budget=budget, mode="vertex", project="test-project")
    assert adapter.is_available
    return adapter, budget


def _scorer(
    adapter: GeminiRubricAdapter,
    budget: CostBudget,
    rows: list[dict[str, Any]] = _ROWS,
    m4_ids: set[str] = _M4_IDS,
    monkeypatch: Any = None,
) -> BenchmarkCanaryScorer:
    monkeypatch.setattr(canary, "_load_benchmark_rows", lambda database_url: rows)
    monkeypatch.setattr(canary, "_load_m4_scored_ids", lambda path=canary.M4_OUTPUTS_PATH: m4_ids)
    return BenchmarkCanaryScorer(database_url="unused", adapter=adapter, cost_budget=budget)


def _controller() -> DriftController:
    return DriftController(
        DriftConfig(window_size=10, min_n=1, drift_entry_threshold=0.3, recovery_threshold=0.6)
    )


def test_select_canary_ids_excludes_all_m4_ids_and_reports_provenance() -> None:
    provenance = select_canary_ids(n=3, benchmark_rows=_ROWS, m4_scored_ids=_M4_IDS)

    assert provenance.eligible_pool_size == 3  # 5 rows - 2 excluded
    assert set(provenance.selected_ids).isdisjoint(_M4_IDS)
    assert len(provenance.selected_ids) <= 3
    assert provenance.excluded_m4_id_count == 2
    assert provenance.seed == canary.CANARY_SEED


def test_select_canary_ids_is_deterministic() -> None:
    first = select_canary_ids(n=3, benchmark_rows=_ROWS, m4_scored_ids=_M4_IDS)
    second = select_canary_ids(n=3, benchmark_rows=_ROWS, m4_scored_ids=_M4_IDS)

    assert first.selected_ids == second.selected_ids
    assert first.excluded_m4_ids_sha256 == second.excluded_m4_ids_sha256


async def test_run_canary_cycle_feeds_controller_and_persists_observations(
    tmp_path: Path, monkeypatch: Any
) -> None:
    adapter, budget = _adapter_and_budget(
        side_effect=[_mock_response(_rubric_response(0.9)) for _ in range(3)]
    )
    scorer = _scorer(adapter, budget, monkeypatch=monkeypatch)
    controller = _controller()
    obs_path = tmp_path / "canary_observations.json"

    report = await scorer.run_canary_cycle(controller, n=3, observations_path=obs_path)

    assert len(report.new_observations) == 3
    assert report.health_record is not None
    assert report.health_record.window_n == 3
    assert not report.budget_stopped_early
    persisted = json.loads(obs_path.read_text())
    assert set(persisted.keys()) == {o.id for o in report.new_observations}
    assert set(persisted.keys()).isdisjoint(_M4_IDS)


async def test_judge_failure_produces_unavailable_observation_not_committed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    adapter, budget = _adapter_and_budget(side_effect=RuntimeError("boom"))
    scorer = _scorer(adapter, budget, monkeypatch=monkeypatch)
    controller = _controller()
    obs_path = tmp_path / "canary_observations.json"

    report = await scorer.run_canary_cycle(controller, n=1, observations_path=obs_path)

    assert len(report.new_observations) == 1
    observation = report.new_observations[0]
    assert observation.status == "model_error"
    assert observation.decision == "unavailable"
    assert report.health_record is not None
    assert report.health_record.committed_n == 0  # excluded from kappa
    assert report.health_record.n_unavailable == 1


async def test_budget_exhaustion_stops_cycle_cleanly_without_recording(
    tmp_path: Path, monkeypatch: Any
) -> None:
    exhausted_budget = CostBudget(per_run_ceiling_usd=0.0)
    adapter, budget = _adapter_and_budget(
        side_effect=[_mock_response(_rubric_response(0.9))], cost_budget=exhausted_budget
    )
    scorer = _scorer(adapter, budget, monkeypatch=monkeypatch)
    controller = _controller()
    obs_path = tmp_path / "canary_observations.json"

    report = await scorer.run_canary_cycle(controller, n=3, observations_path=obs_path)

    assert report.budget_stopped_early
    assert report.new_observations == []
    assert report.health_record is None
    assert not obs_path.exists()


async def test_resumable_cycle_skips_already_scored_ids(tmp_path: Path, monkeypatch: Any) -> None:
    obs_path = tmp_path / "canary_observations.json"
    provenance = select_canary_ids(n=3, benchmark_rows=_ROWS, m4_scored_ids=_M4_IDS)
    already_scored_id = provenance.selected_ids[0]
    obs_path.write_text(
        json.dumps(
            {
                already_scored_id: {
                    "id": already_scored_id,
                    "decision": "supported",
                    "gold_is_hallucination": False,
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "status": "success",
                    "error_detail": None,
                }
            }
        )
    )
    remaining = len(provenance.selected_ids) - 1
    adapter, budget = _adapter_and_budget(
        side_effect=[_mock_response(_rubric_response(0.9)) for _ in range(remaining)]
    )
    scorer = _scorer(adapter, budget, monkeypatch=monkeypatch)
    controller = _controller()

    report = await scorer.run_canary_cycle(controller, n=3, observations_path=obs_path)

    assert len(report.new_observations) == remaining
    assert already_scored_id not in {o.id for o in report.new_observations}
    persisted = json.loads(obs_path.read_text())
    assert len(persisted) == len(provenance.selected_ids)
