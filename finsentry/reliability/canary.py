"""
BenchmarkCanaryScorer: a leakage-free, bounded, resumable benchmark replay
that feeds the live GeminiRubricAdapter and turns its results into
LabeledResults for a caller-owned DriftController.

One concrete class, deliberately. LabeledResult (finsentry/reliability/
health.py) is already the stable seam a future production-label source
(real traffic, human-reviewed) would plug into -- this module does not
build a CanarySource/ProductionLabelSource abstraction ahead of a second
need; see docs/build-log.md's Day 6 Phase 2 entry.

Leakage: the canary pool excludes every id M4 already scored (the full key
set of docs/measurements/calibration/finqa_judge_outputs.json, 500 ids --
not just the 490 committed ones) -- those ids are what the health baseline
(healthy_baseline_kappa=0.6050) was fit on, so re-scoring any of them here
would contaminate monitoring with calibration data. Selection is
deterministic (hash-seeded, reusing finsentry.calibration.split's stratified
sampling) and the provenance (seed, excluded-id count and hash, eligible pool
size, selected ids) is returned so disjointness is a computed artifact, not
a claim.

This module only produces observations. It never decides mode, never
touches decide_ensemble, and never flips the gate -- the caller-owned
DriftController remains the sole authority on state/mode (see controller.py).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from finsentry.calibration.split import stratified_subsample
from finsentry.frontier.adapters.gemini_rubric_adapter import GeminiRubricAdapter
from finsentry.frontier.types import FrontierEvaluationInput, JudgeDecision, JudgeStatus
from finsentry.rails.output.cost_governance import CostBudget
from finsentry.reliability.controller import DriftController
from finsentry.reliability.health import JudgeHealthRecord, LabeledResult

CANARY_SEED = "d6p2-canary-v1"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
M4_OUTPUTS_PATH = _REPO_ROOT / "docs/measurements/calibration/finqa_judge_outputs.json"
CANARY_OBSERVATIONS_PATH = _REPO_ROOT / "docs/measurements/reliability/canary_observations.json"

_BUDGET_EXHAUSTED_DETAIL = "budget_exhausted"


@dataclass(frozen=True)
class CanaryProvenance:
    """Answers "how do you know your monitoring set didn't overlap
    calibration?" with a deterministic artifact rather than a claim."""

    seed: str
    excluded_m4_id_count: int
    excluded_m4_ids_sha256: str
    eligible_pool_size: int
    selected_ids: list[str]


@dataclass(frozen=True)
class CanaryObservation:
    """One scored canary row, persisted to CANARY_OBSERVATIONS_PATH."""

    id: str
    decision: JudgeDecision
    gold_is_hallucination: bool
    observed_at: str
    status: JudgeStatus
    error_detail: str | None


@dataclass(frozen=True)
class CanaryCycleReport:
    provenance: CanaryProvenance
    new_observations: list[CanaryObservation]
    health_record: JudgeHealthRecord | None
    spend_usd: float
    budget_stopped_early: bool


def _load_m4_scored_ids(path: Path = M4_OUTPUTS_PATH) -> set[str]:
    return set(json.loads(path.read_text()).keys())


def _load_benchmark_rows(database_url: str) -> list[dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT id, question, context, response, is_hallucination FROM hallucination_bench"
        ).fetchall()
    return [
        {
            "id": r[0],
            "question": r[1],
            "context": r[2],
            "response": r[3],
            "is_hallucination": r[4],
        }
        for r in rows
    ]


def _load_existing_observations(path: Path) -> dict[str, Any]:
    if path.exists():
        return dict(json.loads(path.read_text()))
    return {}


def _save_observations(path: Path, observations: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(observations, indent=2, sort_keys=True))


def select_canary_ids(
    n: int,
    benchmark_rows: list[dict[str, Any]],
    m4_scored_ids: set[str],
    seed: str = CANARY_SEED,
) -> CanaryProvenance:
    """Pure selection -- no Gemini calls, no I/O beyond what the caller
    already loaded. Excludes every M4-scored id (the full 500-key set, not
    just the 490 committed rows), then deterministically, stratified-ly
    picks up to n ids from what remains, preserving the full benchmark's
    source positive rate (not the eligible-subset rate), matching
    scripts/calibrate_finqa_judge.py's convention for source_positive_rate.
    """
    eligible_rows = [r for r in benchmark_rows if r["id"] not in m4_scored_ids]

    ids_by_label: dict[bool, list[str]] = {True: [], False: []}
    for row in benchmark_rows:
        ids_by_label[bool(row["is_hallucination"])].append(row["id"])
    source_positive_rate = len(ids_by_label[True]) / len(benchmark_rows)

    eligible_ids_by_label: dict[bool, list[str]] = {True: [], False: []}
    for row in eligible_rows:
        eligible_ids_by_label[bool(row["is_hallucination"])].append(row["id"])

    selected_ids = stratified_subsample(eligible_ids_by_label, n, source_positive_rate, seed)

    excluded_sorted = sorted(m4_scored_ids)
    excluded_hash = hashlib.sha256("\n".join(excluded_sorted).encode()).hexdigest()

    return CanaryProvenance(
        seed=seed,
        excluded_m4_id_count=len(m4_scored_ids),
        excluded_m4_ids_sha256=excluded_hash,
        eligible_pool_size=len(eligible_rows),
        selected_ids=selected_ids,
    )


class BenchmarkCanaryScorer:
    """Scores a bounded, leakage-free subset of hallucination_bench through
    a live GeminiRubricAdapter and feeds the results into a caller-owned
    DriftController. Owns its own CostBudget -- never shares the frontier
    consumer's (that budget is ephemeral per-event, not meant to accumulate
    spend across an independent monitoring run)."""

    def __init__(
        self,
        database_url: str,
        adapter: GeminiRubricAdapter | None = None,
        cost_budget: CostBudget | None = None,
        seed: str = CANARY_SEED,
    ) -> None:
        self._database_url = database_url
        self._seed = seed
        self._cost_budget = cost_budget or CostBudget()
        self._adapter = adapter or GeminiRubricAdapter(
            cost_budget=self._cost_budget,
            mode=os.getenv("GEMINI_MODE", "disabled"),
            model_name=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            api_key=os.getenv("GEMINI_API_KEY"),
        )

    async def run_canary_cycle(
        self,
        controller: DriftController,
        n: int,
        observations_path: Path = CANARY_OBSERVATIONS_PATH,
    ) -> CanaryCycleReport:
        """Scores up to n canary rows not yet persisted at observations_path
        (idempotent/resumable -- a prior partial run's scored ids are never
        re-scored). Feeds each result into controller.record_result() as it
        arrives; the controller remains the sole authority on state/mode,
        this method only produces observations."""
        benchmark_rows = _load_benchmark_rows(self._database_url)
        rows_by_id = {row["id"]: row for row in benchmark_rows}
        m4_scored_ids = _load_m4_scored_ids()
        provenance = select_canary_ids(n, benchmark_rows, m4_scored_ids, self._seed)

        existing = _load_existing_observations(observations_path)
        to_score = [row_id for row_id in provenance.selected_ids if row_id not in existing]

        new_observations: list[CanaryObservation] = []
        health_record: JudgeHealthRecord | None = None
        budget_stopped_early = False

        for row_id in to_score:
            row = rows_by_id[row_id]
            evaluation_input = FrontierEvaluationInput(
                app_trace_id=row_id,
                question=row["question"],
                answer=row["response"],
                citations=[],
                retrieved_context_chunks=[row["context"]],
                original_rag_event_ts=datetime.now(UTC).isoformat(),
                peer_retrieval=None,
            )
            result = await self._adapter.evaluate(evaluation_input)

            if result.status == "unavailable" and result.error_detail == _BUDGET_EXHAUSTED_DETAIL:
                budget_stopped_early = True
                break

            # result.decision is "unavailable" for every non-success status
            # (enforced by JudgeResult.__post_init__) -- a timeout/model_error
            # becomes an unavailable LabeledResult, excluded from kappa but
            # counted as evidence. Never recorded as supported/refuted.
            observed_at = datetime.now(UTC).isoformat()
            gold = bool(row["is_hallucination"])
            labeled = LabeledResult(
                decision=result.decision, gold_is_hallucination=gold, observed_at=observed_at
            )
            health_record = controller.record_result(labeled)

            observation = CanaryObservation(
                id=row_id,
                decision=result.decision,
                gold_is_hallucination=gold,
                observed_at=observed_at,
                status=result.status,
                error_detail=result.error_detail,
            )
            new_observations.append(observation)
            existing[row_id] = asdict(observation)
            _save_observations(observations_path, existing)

        return CanaryCycleReport(
            provenance=provenance,
            new_observations=new_observations,
            health_record=health_record,
            spend_usd=self._cost_budget.report()["run_total_usd"],
            budget_stopped_early=budget_stopped_early,
        )
