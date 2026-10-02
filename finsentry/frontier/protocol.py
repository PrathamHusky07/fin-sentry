"""
FrontierJudge protocol.

The orchestrator depends only on this protocol, never on a concrete adapter
class. Adding or removing a judge is a registration-list change in whatever
wires the orchestrator together (the frontier consumer's startup code),
not a change to orchestrator.py itself.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from finsentry.frontier.types import FrontierEvaluationInput, JudgeHealth, JudgeResult


@runtime_checkable
class FrontierJudge(Protocol):
    """A single frontier-tier evaluator.

    judge_id: stable identifier for this judge instance (e.g. "hhem-2.1-open").
    judge_family: the underlying model family (e.g. "hhem", "gemini").
    methodology: the evaluation methodology, not the model — e.g. "nli_premise_hypothesis"
        for HHEM versus "absolute_rubric_scoring" for the Gemini adapter. This is what
        makes two judges complementary rather than two votes on the same question.
    """

    judge_id: str
    judge_family: str
    methodology: str

    async def evaluate(self, evaluation_input: FrontierEvaluationInput) -> JudgeResult: ...

    async def health_check(self) -> JudgeHealth: ...
