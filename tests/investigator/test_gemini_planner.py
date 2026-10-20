"""The live planner's spend accounting and failure handling, with a stand-in client."""

from __future__ import annotations

import inspect
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


# The request deadline and the accounting around it.


async def test_every_request_carries_a_transport_deadline_below_the_loops_model_timeout() -> None:
    from finsentry.investigator.gemini_planner import REQUEST_TIMEOUT_S
    from finsentry.investigator.loop import BoundedInvestigator

    client = FakeClient(PLAN.model_dump_json())
    await GeminiPlanner(client, "gemini-test").plan("digest", round_no=1)
    options = client.calls[0]["config"].http_options
    assert options.timeout == int(REQUEST_TIMEOUT_S * 1000)  # milliseconds, as the SDK reads it
    loop_timeout = inspect.signature(BoundedInvestigator.__init__).parameters["model_timeout_s"]
    assert REQUEST_TIMEOUT_S < loop_timeout.default


async def test_the_deadline_can_be_set_per_planner() -> None:
    client = FakeClient(PLAN.model_dump_json())
    await GeminiPlanner(client, "gemini-test", request_timeout_s=12.5).plan("digest", round_no=1)
    assert client.calls[0]["config"].http_options.timeout == 12500


async def test_a_request_that_raises_is_charged_at_a_pessimistic_estimate() -> None:
    class Raises:
        models = SimpleNamespace(
            generate_content=lambda **_: (_ for _ in ()).throw(TimeoutError("read timed out"))
        )

    planner = GeminiPlanner(Raises(), "gemini-test")
    with pytest.raises(TimeoutError):
        await planner.plan("x" * 3000, round_no=1)
    assert planner.calls == 1 and planner.unmetered_calls == 1
    assert planner.cost_usd > 4096 * 3.75 / 1_000_000  # at least the whole output allowance


async def test_a_wait_that_is_cancelled_charges_the_call_and_blocks_an_overlapping_retry() -> None:
    """Cancelling the awaiting coroutine does not stop the blocking request, and this test
    does not claim it does. It shows the call is still charged and that no second request
    starts until the first has left its thread."""
    import asyncio
    import threading

    release = threading.Event()

    class Slow:
        def __init__(self) -> None:
            self.started = 0
            self.models = SimpleNamespace(generate_content=self._generate)

        def _generate(self, **_: Any) -> Any:
            self.started += 1
            release.wait(5)
            return FakeClient(PLAN.model_dump_json())._response

    client = Slow()
    planner = GeminiPlanner(client, "gemini-test")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(planner.plan("digest", round_no=1), 0.05)
    assert planner.unmetered_calls == 1 and planner.cost_usd > 0
    with pytest.raises(PlanningError, match="still running"):
        await planner.plan("digest", round_no=1)
    assert client.started == 1, "the retry never reached the SDK"
    release.set()
    for _ in range(100):
        if planner._idle.is_set():
            break
        await asyncio.sleep(0.01)
    assert await planner.plan("digest", round_no=1) == PLAN
    assert client.started == 2
