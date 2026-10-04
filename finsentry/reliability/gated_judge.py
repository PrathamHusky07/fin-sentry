"""
DriftGatedJudge: admission control in front of the FrontierJudge protocol.

Wraps any FrontierJudge with a DriftController and intercepts evaluate()
when the controller's mode is frontier_only -- it returns a synthesized
unavailable JudgeResult without calling the wrapped judge at all, and never
constructs or imports anything from finsentry.frontier.ensemble.
decide_ensemble() is not touched: it already knows exactly what to do with a
JudgeResult(status="unavailable") (see docs/build-log.md's Day 6 Phase 0
entry on why this is the mechanism, not a new decision path). judge_id/
judge_family/methodology are passed through unchanged so the orchestrator,
decide_ensemble, and any downstream consumer see the same judge identity
whether or not it is currently gated.
"""
from __future__ import annotations

from finsentry.frontier.protocol import FrontierJudge
from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult
from finsentry.reliability.controller import DriftController

_DRIFT_BYPASS_ERROR_DETAIL = "judge_drift_bypass: operating_mode=frontier_only"


class DriftGatedJudge:
    def __init__(self, judge: FrontierJudge, controller: DriftController) -> None:
        self._judge = judge
        self._controller = controller
        self.judge_id = judge.judge_id
        self.judge_family = judge.judge_family
        self.methodology = judge.methodology

    @property
    def controller(self) -> DriftController:
        return self._controller

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult:
        if self._controller.current_mode == "frontier_only":
            return JudgeResult(
                judge_id=self.judge_id,
                judge_family=self.judge_family,
                methodology=self.methodology,
                status="unavailable",
                error_detail=_DRIFT_BYPASS_ERROR_DETAIL,
            )
        return await self._judge.evaluate(evaluation_input)

    async def health_check(self) -> JudgeHealth:
        """Always delegates: operational liveness is independent of drift
        bypass -- a judge can be technically reachable while bypassed for
        accuracy drift, and that distinction matters to anyone reading
        JudgeHealth."""
        return await self._judge.health_check()
