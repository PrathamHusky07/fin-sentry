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
from finsentry.investigator.gemini_planner import (
    SESSION_COST_CAP_USD,
    GeminiPlanner,
    session_ledger,
    worst_case_cost_usd,
)
from finsentry.investigator.planning import Plan, PlanningError
from finsentry.rails.output.cost_governance import CostBudget

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
    first_worst = worst_case_cost_usd("digest")
    # Room for one call's worst case and a little more, so the second call is the one refused.
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=first_worst + 0.004)
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


# Strict reservation: the worst case of the next call is checked against what is left before the
# call starts, and the actual usage is reconciled after.


async def test_a_call_whose_worst_case_would_breach_the_cap_never_starts() -> None:
    client = FakeClient(PLAN.model_dump_json())
    # The reply would cost $0.006, under this cap, but the worst case of the call is far above it.
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=0.01)
    with pytest.raises(PlanningError, match="cost cap"):
        await planner.plan("digest", round_no=1)
    assert client.calls == [] and planner.cost_usd == 0 and planner.calls == 0


async def test_the_reservation_covers_the_prompt_the_output_allowance_and_thinking() -> None:
    from finsentry.investigator.gemini_planner import (
        MAX_OUTPUT_TOKENS,
        THINKING_BUDGET,
        system_prompt,
    )

    digest = "x" * 9000
    prompt_tokens = (len(system_prompt()) + len(digest)) // 3
    floor = CostBudget.estimate_call_cost(prompt_tokens, MAX_OUTPUT_TOKENS, THINKING_BUDGET)
    assert worst_case_cost_usd(digest) >= floor
    assert worst_case_cost_usd(digest) > worst_case_cost_usd("short")


async def test_the_cap_is_a_boundary_on_spent_plus_the_next_worst_case() -> None:
    client = FakeClient(PLAN.model_dump_json())
    actual = CostBudget.estimate_call_cost(3000, 800, 200)
    worst = worst_case_cost_usd("digest")
    just_short = GeminiPlanner(client, "gemini-test", cost_cap_usd=actual + worst - 0.0001)
    await just_short.plan("digest", round_no=1)  # nothing spent yet, so the first call fits
    with pytest.raises(PlanningError, match="cost cap"):
        await just_short.plan("digest", round_no=2)
    enough = GeminiPlanner(client, "gemini-test", cost_cap_usd=actual + worst + 0.0001)
    await enough.plan("digest", round_no=1)
    await enough.plan("digest", round_no=2)
    assert enough.cost_usd == pytest.approx(2 * actual)


async def test_the_reservation_is_reconciled_to_actual_usage_after_each_call() -> None:
    planner = GeminiPlanner(FakeClient(PLAN.model_dump_json()), "gemini-test")
    await planner.plan("digest", round_no=1)
    assert planner.cost_usd == pytest.approx(CostBudget.estimate_call_cost(3000, 800, 200))
    assert planner.cost_usd < worst_case_cost_usd("digest")


# The session cap is shared by every planner in the process and holds on its own.


async def test_a_second_planner_cannot_reset_the_session_cap() -> None:
    # Room for one call's worst case (about $0.021) and not for a second one after $0.006 spent.
    ledger = CostBudget(per_run_ceiling_usd=0.025, per_day_ceiling_usd=0.025)
    client = FakeClient(PLAN.model_dump_json())
    first = GeminiPlanner(client, "gemini-test", ledger=ledger)
    await first.plan("digest", round_no=1)
    second = GeminiPlanner(client, "gemini-test", ledger=ledger)  # a fresh instance, a fresh cap
    with pytest.raises(PlanningError, match="session"):
        await second.plan("digest", round_no=1)
    assert len(client.calls) == 1, "the second planner never reached the SDK"


async def test_the_session_cap_holds_even_when_the_planner_cap_is_generous() -> None:
    ledger = CostBudget(per_run_ceiling_usd=0.01, per_day_ceiling_usd=0.01)
    client = FakeClient(PLAN.model_dump_json())
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=5.0, ledger=ledger)
    with pytest.raises(PlanningError, match="session"):
        await planner.plan("digest", round_no=1)  # the worst case alone is above $0.01
    assert client.calls == []


async def test_the_planner_cap_holds_even_when_the_session_has_room() -> None:
    ledger = CostBudget(per_run_ceiling_usd=100.0, per_day_ceiling_usd=100.0)
    client = FakeClient(PLAN.model_dump_json())
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=0.01, ledger=ledger)
    with pytest.raises(PlanningError, match="planner's cost cap"):
        await planner.plan("digest", round_no=1)
    assert client.calls == []


async def test_a_call_charged_at_an_estimate_counts_against_the_session_too() -> None:
    class Raises:
        models = SimpleNamespace(generate_content=lambda **_: (_ for _ in ()).throw(OSError("x")))

    ledger = CostBudget(per_run_ceiling_usd=1.0, per_day_ceiling_usd=1.0)
    planner = GeminiPlanner(Raises(), "gemini-test", ledger=ledger)
    with pytest.raises(OSError):
        await planner.plan("digest", round_no=1)
    assert ledger.report()["run_total_usd"] == pytest.approx(planner.cost_usd, abs=1e-6)
    assert ledger.report()["call_count"] == 1


async def test_a_metered_call_is_charged_to_the_session_at_its_actual_usage() -> None:
    ledger = CostBudget(per_run_ceiling_usd=1.0, per_day_ceiling_usd=1.0)
    planner = GeminiPlanner(FakeClient(PLAN.model_dump_json()), "gemini-test", ledger=ledger)
    await planner.plan("digest", round_no=1)
    assert ledger.report()["run_total_usd"] == pytest.approx(planner.cost_usd, abs=1e-6)


def test_the_process_session_ledger_is_one_object_with_the_session_cap() -> None:
    assert session_ledger() is session_ledger()
    assert SESSION_COST_CAP_USD == 0.10
    assert session_ledger().report()["ceilings"]["per_run_usd"] == SESSION_COST_CAP_USD


# Two planners that share a ledger compete for one remaining allowance. A check that only reads
# the ledger lets both pass before either has spent, so the second must see the first's reservation.


class Gated:
    """A client whose request blocks until released, so two requests can overlap."""

    def __init__(self) -> None:
        import threading

        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **_: Any) -> Any:
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        return FakeClient(PLAN.model_dump_json())._response


async def _until(event: Any) -> None:
    import asyncio

    for _ in range(200):
        if event.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the request never started")


async def test_two_planners_cannot_both_spend_the_same_remaining_allowance() -> None:
    import asyncio

    worst = worst_case_cost_usd("digest")
    # Room for one worst case and not for two.
    ledger = CostBudget(per_run_ceiling_usd=worst * 1.5, per_day_ceiling_usd=worst * 1.5)
    slow = Gated()
    fast = FakeClient(PLAN.model_dump_json())
    first = GeminiPlanner(slow, "gemini-test", cost_cap_usd=5.0, ledger=ledger)
    second = GeminiPlanner(fast, "gemini-test", cost_cap_usd=5.0, ledger=ledger)
    running = asyncio.create_task(first.plan("digest", round_no=1))
    await _until(slow.started)
    with pytest.raises(PlanningError, match="session"):
        await second.plan("digest", round_no=1)
    assert fast.calls == [], "the second planner reached the SDK on the first one's allowance"
    slow.release.set()
    assert await running == PLAN


async def test_the_reservation_is_released_when_the_call_ends_so_later_calls_fit() -> None:
    worst = worst_case_cost_usd("digest")
    actual = CostBudget.estimate_call_cost(3000, 800, 200)
    ledger = CostBudget(per_run_ceiling_usd=worst + actual + 0.001, per_day_ceiling_usd=5.0)
    client = FakeClient(PLAN.model_dump_json())
    planner = GeminiPlanner(client, "gemini-test", cost_cap_usd=5.0, ledger=ledger)
    await planner.plan("digest", round_no=1)
    assert ledger.reserved_usd == 0.0
    await planner.plan("digest", round_no=2)  # fits only if the first reservation was released
    assert len(client.calls) == 2 and ledger.reserved_usd == 0.0


async def test_the_reservation_is_released_when_the_call_fails_or_the_reply_is_unusable() -> None:
    ledger = CostBudget(per_run_ceiling_usd=1.0, per_day_ceiling_usd=1.0)
    bad = GeminiPlanner(FakeClient('{"hypotheses": []}'), "gemini-test", ledger=ledger)
    with pytest.raises(PlanningError):
        await bad.plan("digest", round_no=1)
    assert ledger.reserved_usd == 0.0

    class Raises:
        models = SimpleNamespace(generate_content=lambda **_: (_ for _ in ()).throw(OSError("x")))

    broken = GeminiPlanner(Raises(), "gemini-test", ledger=ledger)
    with pytest.raises(OSError):
        await broken.plan("digest", round_no=1)
    assert ledger.reserved_usd == 0.0


async def test_a_failed_call_is_charged_at_the_same_worst_case_it_reserved_and_not_twice() -> None:
    """Output and thinking tokens are separate counts in the cost model, both billed at the
    output rate, and the reservation counts the whole of each. A call that may have run with no
    usage to read is charged that same worst case, once: the reservation is released as the
    charge is recorded, so the ledger holds the charge and nothing extra."""

    class Raises:
        models = SimpleNamespace(generate_content=lambda **_: (_ for _ in ()).throw(OSError("x")))

    ledger = CostBudget(per_run_ceiling_usd=1.0, per_day_ceiling_usd=1.0)
    planner = GeminiPlanner(Raises(), "gemini-test", ledger=ledger)
    with pytest.raises(OSError):
        await planner.plan("digest", round_no=1)
    assert planner.cost_usd == pytest.approx(worst_case_cost_usd("digest"))
    assert ledger.report()["run_total_usd"] == pytest.approx(
        worst_case_cost_usd("digest"), abs=1e-6
    )
    assert ledger.reserved_usd == 0.0
