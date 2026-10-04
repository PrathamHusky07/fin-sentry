"""
Proves the closed loop: a drifted judge's result is admitted as unavailable,
and M3's real, unmodified decide_ensemble() produces the single_judge /
ensemble_insufficient outcome it already produces for any unavailable judge --
no new branching logic. This is the keystone the Day 6 Phase 0 build-log
entry names: M3's unavailable semantics used operationally, not theoretically.
"""
from __future__ import annotations

from finsentry.frontier.ensemble import decide_ensemble
from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult
from finsentry.reliability.controller import DriftController
from finsentry.reliability.gated_judge import DriftGatedJudge
from finsentry.reliability.health import DriftConfig, LabeledResult

_T0 = "2026-01-01T00:00:00+00:00"

_CFG = DriftConfig(
    window_size=1,
    min_n=1,
    drift_entry_threshold=0.3,
    recovery_threshold=0.6,
    entry_consecutive_windows=2,
    recovery_consecutive_windows=3,
)


class _StubJudge:
    """Minimal FrontierJudge double -- returns a canned success verdict and
    records whether evaluate() was actually called, so tests can prove the
    underlying (expensive) judge is skipped entirely when bypassed."""

    def __init__(self, judge_id: str, decision: str = "supported") -> None:
        self.judge_id = judge_id
        self.judge_family = judge_id
        self.methodology = "stub"
        self.evaluate_call_count = 0
        self._decision = decision

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        self.evaluate_call_count += 1
        score = 0.9 if self._decision == "supported" else 0.1
        return JudgeResult(
            judge_id=self.judge_id,
            judge_family=self.judge_family,
            methodology=self.methodology,
            status="success",
            decision=self._decision,  # type: ignore[arg-type]
            faithfulness_score=score,
        )

    async def health_check(self) -> JudgeHealth:
        return JudgeHealth(
            judge_id=self.judge_id, status="healthy", last_success_ts=None, error_rate_1h=0.0
        )


def _eval_input() -> FrontierEvaluationInput:
    return FrontierEvaluationInput(
        app_trace_id="trace-1",
        question="q",
        answer="a",
        citations=[],
        retrieved_context_chunks=["chunk"],
        original_rag_event_ts="2026-01-01T00:00:00+00:00",
    )


async def test_normal_mode_delegates_to_the_underlying_judge() -> None:
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)

    result = await gated.evaluate(_eval_input())

    assert stub.evaluate_call_count == 1
    assert result.status == "success"
    assert result.decision == "supported"


async def test_drifted_mode_bypasses_the_underlying_judge_without_calling_it() -> None:
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)

    # Drive to drifted (K=2 consecutive breaches).
    bad = LabeledResult("supported", True, observed_at=_T0)
    for _ in range(2):
        controller.record_result(bad)
    assert controller.current_mode == "frontier_only"

    result = await gated.evaluate(_eval_input())

    assert stub.evaluate_call_count == 0  # underlying judge never called
    assert result.status == "unavailable"
    assert result.decision == "unavailable"
    assert result.judge_id == "gemini-rubric"  # identity preserved even while bypassed


async def test_health_check_always_delegates_regardless_of_drift_mode() -> None:
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)
    for _ in range(2):
        controller.record_result(LabeledResult("supported", True, observed_at=_T0))
    assert controller.current_mode == "frontier_only"

    health = await gated.health_check()
    assert health.status == "healthy"  # operational liveness, independent of drift bypass


async def test_closed_loop_single_judge_bypassed_produces_ensemble_insufficient() -> None:
    """The exact scenario named in the build log: HHEM disabled (today's
    default), GeminiRubricAdapter drifted -> both judges now report
    unavailable -> decide_ensemble (untouched) falls through to its
    pre-existing all_unavailable branch. No new logic in decide_ensemble."""
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)
    for _ in range(2):
        controller.record_result(LabeledResult("supported", True, observed_at=_T0))
    assert controller.current_mode == "frontier_only"

    gated_result = await gated.evaluate(_eval_input())
    outcome = decide_ensemble([gated_result])  # HHEM disabled -- this is the only judge

    assert outcome.verdict == "ensemble_insufficient"
    assert outcome.disagreement_taxonomy == "all_unavailable"


async def test_closed_loop_with_a_second_live_judge_produces_single_judge() -> None:
    """Same bypass, but with a second (e.g. HHEM) judge enabled and healthy
    -- decide_ensemble's pre-existing single_judge branch takes over,
    exactly as it already does for any one-live-judge-left scenario."""
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)
    for _ in range(2):
        controller.record_result(LabeledResult("supported", True, observed_at=_T0))

    gated_result = await gated.evaluate(_eval_input())
    second_judge_result = JudgeResult(
        judge_id="hhem-2.1-open",
        judge_family="hhem",
        methodology="nli_premise_hypothesis",
        status="success",
        decision="refuted",
        faithfulness_score=0.1,
    )
    outcome = decide_ensemble([gated_result, second_judge_result])

    assert outcome.verdict == "ensemble_refuted"
    assert outcome.disagreement_taxonomy == "single_judge"


async def test_readmission_after_sustained_recovery_calls_underlying_judge_again() -> None:
    """Phase 1-3's recovery test proved the controller's mode returns to
    normal; this proves the consequence that actually matters operationally
    -- DriftGatedJudge.evaluate() calls the wrapped (expensive) judge again
    once re-admitted, not just that the controller's internal mode flag
    flipped. Call count must increment only during the normal/recovered
    phases, never during the drifted phase."""
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)

    # normal: underlying evaluate() IS called.
    result = await gated.evaluate(_eval_input())
    assert stub.evaluate_call_count == 1
    assert result.status == "success"

    # Drive to drifted (K=2 consecutive breaches, per _CFG).
    bad = LabeledResult("supported", True, observed_at=_T0)
    for _ in range(2):
        controller.record_result(bad)
    assert controller.current_mode == "frontier_only"

    # drifted: underlying evaluate() is NOT called (synthesized unavailable),
    # repeated calls confirm the call count never advances while bypassed.
    for _ in range(3):
        result = await gated.evaluate(_eval_input())
        assert result.status == "unavailable"
    assert stub.evaluate_call_count == 1

    # Drive sustained recovery (M=3 consecutive recovery-grade windows, per _CFG).
    good = LabeledResult("refuted", True, observed_at=_T0)
    for _ in range(3):
        controller.record_result(good)
    assert controller.current_mode == "normal"

    # re-admitted: underlying evaluate() IS called again.
    result = await gated.evaluate(_eval_input())
    assert stub.evaluate_call_count == 2
    assert result.status == "success"


async def test_proof_b_synthetic_closed_loop_healthy_to_drifted_to_recovered() -> None:
    """Day 6 Phase 2 Proof B: the closed-loop control-behavior proof, through
    the real DriftController + DriftGatedJudge + unmodified decide_ensemble().
    Every LabeledResult here is injected/synthetic, NOT live Gemini -- this
    proves the mechanism reacts correctly to a given kappa sequence, it does
    NOT claim the live Gemini judge actually drifted (see Proof A in
    docs/build-log.md for the live, un-staged canary run)."""
    stub = _StubJudge("gemini-rubric")
    controller = DriftController(_CFG)
    gated = DriftGatedJudge(stub, controller)

    # 1. healthy: underlying judge is called, decide_ensemble gets a real verdict.
    result = await gated.evaluate(_eval_input())
    assert result.status == "success"
    assert decide_ensemble([result]).disagreement_taxonomy == "single_judge"

    # 2. sustained degradation (K=2 consecutive breaches, per _CFG) -> drifted + frontier_only.
    bad = LabeledResult("supported", True, observed_at=_T0)
    for _ in range(2):
        controller.record_result(bad)
    assert controller.current_state == "drifted"
    assert controller.current_mode == "frontier_only"

    # 3. gated judge bypassed -- the bypassed result feeds the real, unmodified
    # decide_ensemble, which (HHEM disabled, today's default) falls through
    # to its pre-existing all_unavailable branch. No new logic anywhere.
    gated_result = await gated.evaluate(_eval_input())
    assert stub.evaluate_call_count == 1  # unchanged -- underlying judge not called again
    assert gated_result.status == "unavailable"
    outcome = decide_ensemble([gated_result])
    assert outcome.verdict == "ensemble_insufficient"
    assert outcome.disagreement_taxonomy == "all_unavailable"

    # 4. sustained recovery (M=3 consecutive recovery-grade windows, per _CFG) -> normal.
    good = LabeledResult("refuted", True, observed_at=_T0)
    for _ in range(3):
        controller.record_result(good)
    assert controller.current_state == "healthy"
    assert controller.current_mode == "normal"

    # 5. re-admitted: underlying judge is called again.
    result = await gated.evaluate(_eval_input())
    assert stub.evaluate_call_count == 2
    assert result.status == "success"
