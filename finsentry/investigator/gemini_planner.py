"""
The live planner: one Gemini call per planning round, structured output, hard cost cap.

It is the only place the investigator spends money. Each call returns a Plan that the loop
validates before using any of it. Spend is counted from the response's own usage metadata at
the platform's published rates (rails/output/cost_governance.py), and the planner refuses a
call once its running total reaches the cap, so a bad prompt loop cannot run up a bill.

Timeouts. The SDK call is synchronous and runs in a worker thread, so cancelling the awaiting
coroutine (the loop's asyncio.wait_for) stops the wait and does not stop the request. The only
deadline that ends the request is the transport's. google-genai 2.x passes
HttpOptions.timeout, in milliseconds, to httpx as the request timeout, and also sends it as the
X-Server-Timeout header. The planner sets it on every request to REQUEST_TIMEOUT_S, which is
below the loop's model timeout, so the request normally ends before the loop gives up on it.
httpx applies that value to each phase of the request, so it bounds a single non-streaming
reply and is not a total wall-clock guarantee.

Two guards cover the case where the loop gives up first. A call that raises or is cancelled
after the request was sent is charged at a pessimistic estimate, because the model may have
run and been billed with no usage metadata to read. And a new request is refused while an
earlier one is still in its thread, so a retry never overlaps a request that is still running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

from pydantic import ValidationError

from finsentry.investigator.digest import SYSTEM_PROMPT
from finsentry.investigator.planning import Plan, PlanningError
from finsentry.rails.output.cost_governance import CostBudget

log = logging.getLogger(__name__)

DEFAULT_COST_CAP_USD = 0.25  # half of the session cap, so an estimate that is off still holds
MAX_OUTPUT_TOKENS = 4096
THINKING_BUDGET = 1024  # thinking tokens are billed as output, so they are bounded too
REQUEST_TIMEOUT_S = 30.0  # below the loop's 45 s model timeout
CHARS_PER_TOKEN = 3  # a pessimistic ratio, so an estimate from text errs high


def system_prompt() -> str:
    """The instructions plus the plan schema. Vertex rejects this schema as a response_schema
    (HTTP 400), so it is given in the prompt and the reply is validated here instead."""
    schema = json.dumps(Plan.model_json_schema(), separators=(",", ":"))
    return f"{SYSTEM_PROMPT}\nThe JSON must match this JSON schema exactly:\n{schema}\n"


class GeminiPlanner:
    name = "gemini-planner"

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        cost_cap_usd: float = DEFAULT_COST_CAP_USD,
        request_timeout_s: float = REQUEST_TIMEOUT_S,
    ) -> None:
        self._client = client
        self._model = model
        self._cap = cost_cap_usd
        self._request_timeout_s = request_timeout_s
        self._idle = threading.Event()
        self._idle.set()  # cleared while a request is in its worker thread
        self.cost_usd = 0.0
        self.calls = 0
        self.unmetered_calls = 0  # calls charged at an estimate because no usage came back
        self.tokens = {"prompt": 0, "candidates": 0, "thoughts": 0}
        self.name = f"gemini-planner:{model}"

    @classmethod
    def from_env(cls, *, cost_cap_usd: float = DEFAULT_COST_CAP_USD) -> GeminiPlanner:
        from dotenv import load_dotenv
        from google import genai

        load_dotenv()
        mode = os.getenv("GEMINI_MODE", "disabled")
        model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        if mode == "vertex":
            client = genai.Client(
                vertexai=True,
                project=os.environ["GOOGLE_CLOUD_PROJECT"],
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            )
        elif mode == "developer":
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        else:
            raise PlanningError(f"GEMINI_MODE is {mode!r}, so there is no model to call")
        return cls(client, model, cost_cap_usd=cost_cap_usd)

    def _call(self, digest: str) -> Any:
        from google.genai import types

        return self._client.models.generate_content(
            model=self._model,
            contents=digest,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt(),
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
                http_options=types.HttpOptions(timeout=int(self._request_timeout_s * 1000)),
            ),
        )

    def _call_in_thread(self, digest: str) -> Any:
        try:
            return self._call(digest)
        finally:
            self._idle.set()

    def _charge_unmetered(self, digest: str) -> None:
        """Charge a call that may have run with no usage to read: every input token the text
        could hold, and the whole output allowance."""
        prompt = (len(system_prompt()) + len(digest)) // CHARS_PER_TOKEN
        self.calls += 1
        self.unmetered_calls += 1
        self.cost_usd += CostBudget.estimate_call_cost(prompt, MAX_OUTPUT_TOKENS, 0)

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        if self.cost_usd >= self._cap:
            raise PlanningError(f"the planner's cost cap of ${self._cap:.2f} is reached")
        if not self._idle.is_set():
            raise PlanningError("an earlier model request is still running, so none is started")
        self._idle.clear()
        try:
            response = await asyncio.to_thread(self._call_in_thread, digest)
        except BaseException:  # a failure or a cancelled wait: the request may still be billed
            self._charge_unmetered(digest)
            raise
        usage = response.usage_metadata
        prompt = (usage.prompt_token_count or 0) if usage else 0
        candidates = (usage.candidates_token_count or 0) if usage else 0
        thoughts = (usage.thoughts_token_count or 0) if usage else 0
        self.calls += 1
        self.tokens["prompt"] += prompt
        self.tokens["candidates"] += candidates
        self.tokens["thoughts"] += thoughts
        self.cost_usd += CostBudget.estimate_call_cost(prompt, candidates, thoughts)
        text = response.text or ""
        try:
            return Plan.model_validate_json(text)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first["loc"])
            raise PlanningError(
                f"the plan did not match the schema, {exc.error_count()} errors, first at "
                f"{where}: {first['msg']}"
            ) from exc
