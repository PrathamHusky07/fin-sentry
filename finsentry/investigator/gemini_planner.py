"""
The live planner: one Gemini call per planning round, structured output, hard cost cap.

It is the only place the investigator spends money. Each call returns a Plan that the loop
validates before using any of it. Spend is counted from the response's own usage metadata at
the platform's published rates (rails/output/cost_governance.py), and the planner refuses a
call once its running total reaches the cap, so a bad prompt loop cannot run up a bill.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from pydantic import ValidationError

from finsentry.investigator.digest import SYSTEM_PROMPT
from finsentry.investigator.planning import Plan, PlanningError
from finsentry.rails.output.cost_governance import CostBudget

log = logging.getLogger(__name__)

DEFAULT_COST_CAP_USD = 0.25  # half of the session cap, so an estimate that is off still holds
MAX_OUTPUT_TOKENS = 4096


class GeminiPlanner:
    name = "gemini-planner"

    def __init__(
        self, client: Any, model: str, *, cost_cap_usd: float = DEFAULT_COST_CAP_USD
    ) -> None:
        self._client = client
        self._model = model
        self._cap = cost_cap_usd
        self.cost_usd = 0.0
        self.calls = 0
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
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=Plan,
                temperature=0.0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        if self.cost_usd >= self._cap:
            raise PlanningError(f"the planner's cost cap of ${self._cap:.2f} is reached")
        response = await asyncio.to_thread(self._call, digest)
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
            raise PlanningError(
                f"the plan did not match the schema: {exc.error_count()} errors"
            ) from exc
