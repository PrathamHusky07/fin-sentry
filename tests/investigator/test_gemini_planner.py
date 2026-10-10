"""The live planner's spend accounting and failure handling, with a stand-in client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from finsentry.investigator.evaluation.planner_double import (
    hypothesis,
    prediction,
)
from finsentry.investigator.gemini_planner import GeminiPlanner
from finsentry.investigator.planning import Plan, PlanningError

PLAN = Plan(
    hypotheses=[
        hypothesis("h1", "s", "judges", "j", prediction("get_drift_report", "judge_drift", "d")),
        hypothesis(
            "h2",
            "s",
            "retrieval",
            "r",
            prediction("get_drift_report", "judge_drift", "d", expect=False),
        ),
    ]
)


class FakeClient:
    def __init__(self, text: str, prompt: int = 3000, out: int = 800, thoughts: int = 200) -> None:
        self.calls: list[dict[str, Any]] = []
        usage = SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        )
        self._response = SimpleNamespace(text=text, usage_metadata=usage)
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


async def test_a_valid_plan_is_returned_and_its_cost_counted_from_usage() -> None:
    client = FakeClient(PLAN.model_dump_json())
    planner = GeminiPlanner(client, "gemini-test")
    plan = await planner.plan("digest", round_no=1)
    assert plan == PLAN
    # 3000 input tokens at $0.75 per million plus 1000 output and thinking tokens at $3.75.
    assert planner.cost_usd == pytest.approx(0.00225 + 0.00375)
    assert planner.calls == 1 and planner.tokens == {
        "prompt": 3000,
        "candidates": 800,
        "thoughts": 200,
    }
    config = client.calls[0]["config"]
    assert config.response_mime_type == "application/json" and config.temperature == 0.0


async def test_a_reply_that_is_not_a_plan_is_a_planning_error_but_still_costs() -> None:
    planner = GeminiPlanner(FakeClient('{"hypotheses": []}'), "gemini-test")
    with pytest.raises(PlanningError):
        await planner.plan("digest", round_no=1)
    assert planner.cost_usd > 0


async def test_a_planner_at_its_cost_cap_makes_no_further_call() -> None:
    client = FakeClient(PLAN.model_dump_json())
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=0.005)
    await planner.plan("digest", round_no=1)
    with pytest.raises(PlanningError, match="cost cap"):
        await planner.plan("digest", round_no=2)
    assert len(client.calls) == 1

