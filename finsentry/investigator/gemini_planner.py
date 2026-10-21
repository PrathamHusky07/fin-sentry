"""
The live planner: one Gemini call per planning round, structured output, hard cost cap.

It is the only place the investigator spends money. Each call returns a Plan that the loop
validates before using any of it. Spend is counted from the response's own usage metadata at
the platform's published rates (rails/output/cost_governance.py).

Strict reservation. Before a request starts, the planner reserves its worst case, which is every
input token the text could hold plus the whole output and thinking allowance. The check against
the planner's cap and the hold on the session ledger are one step under the ledger's lock, so two
planners that share the ledger cannot both spend the same remaining allowance. Actual usage is
recorded, then the hold is released. Two caps apply and neither depends on the other: the
planner's own, and the session ledger shared by every planner in the process, so a new planner
instance does not reset the session. The ledger lives in one process and is not shared between
replicas or restarts, the limit CostBudget already documents.

Governance contract. The planner is governed by run and session ceilings only: its own
cost_cap_usd and the shared ledger's per-run and per-day ceilings, checked by reserve(). It does
not enforce the ledger's per-call ceiling. That ceiling is the judges' policy, applied by
can_proceed() in the faithfulness metrics and the Gemini rubric adapter, and nothing in the
investigator calls can_proceed(). The planner's worst case (about $0.021) is above the $0.02
per-call constant by design, so wiring that constant into reserve() would refuse every request.

Tokens. The cost model keeps output and thinking as two counts, candidates and thoughts, both
billed at the output rate. The reservation holds the whole of each, and a call that may have run
with no usage to read is charged that same worst case, once.

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

DEFAULT_COST_CAP_USD = 0.25
SESSION_COST_CAP_USD = 0.10  # the Day 11.2 session cap across every planner in this process
MAX_OUTPUT_TOKENS = 4096
THINKING_BUDGET = 1024  # thinking tokens are billed as output, so they are bounded too
REQUEST_TIMEOUT_S = 30.0  # below the loop's 45 s model timeout
CHARS_PER_TOKEN = 3  # a pessimistic ratio, so an estimate from text errs high


_SESSION = CostBudget(
    per_run_ceiling_usd=SESSION_COST_CAP_USD, per_day_ceiling_usd=SESSION_COST_CAP_USD
)


def session_ledger() -> CostBudget:
    """The one ledger every planner built by from_env charges."""
    return _SESSION


def system_prompt() -> str:
    """The instructions plus the plan schema. Vertex rejects this schema as a response_schema
    (HTTP 400), so it is given in the prompt and the reply is validated here instead."""
    schema = json.dumps(Plan.model_json_schema(), separators=(",", ":"))
    return f"{SYSTEM_PROMPT}\nThe JSON must match this JSON schema exactly:\n{schema}\n"


def _prompt_tokens_upper(digest: str) -> int:
    """Every input token the request text could hold, at a pessimistic characters-per-token
    ratio."""
    return (len(system_prompt()) + len(digest)) // CHARS_PER_TOKEN + 1


def _token_count(value: object) -> int | None:
    """A usable token count, or None for a missing or invalid one."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _read_usage(usage: Any) -> tuple[int, int, int] | None:
    """The prompt, candidate and thinking counts of a reply, or None when the reply cannot be
    priced. No usage record, or a prompt or candidate count that is missing or invalid, is
    None, and the caller charges the reserved worst case instead of zero. A missing thinking
    count alone is read as zero: the SDK leaves it unset when the model did not think."""
    if usage is None:
        return None
    prompt = _token_count(getattr(usage, "prompt_token_count", None))
    candidates = _token_count(getattr(usage, "candidates_token_count", None))
    if prompt is None or candidates is None:
        return None
    thoughts = getattr(usage, "thoughts_token_count", None)
    if thoughts is None:
        return prompt, candidates, 0
    thoughts_ok = _token_count(thoughts)
    return None if thoughts_ok is None else (prompt, candidates, thoughts_ok)


def worst_case_cost_usd(digest: str) -> float:
    """The most one request can cost: the prompt at a pessimistic characters-per-token ratio,
    the whole output allowance and the whole thinking budget, all at the platform's rates."""
    return CostBudget.estimate_call_cost(
        _prompt_tokens_upper(digest), MAX_OUTPUT_TOKENS, THINKING_BUDGET
    )


class GeminiPlanner:
    name = "gemini-planner"

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        cost_cap_usd: float = DEFAULT_COST_CAP_USD,
        request_timeout_s: float = REQUEST_TIMEOUT_S,
        ledger: CostBudget | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._cap = cost_cap_usd
        self._ledger = ledger
        self._request_timeout_s = request_timeout_s
        self._idle = threading.Event()
        self._idle.set()  # cleared while a request is in its worker thread
        self.cost_usd = 0.0
        self.calls = 0
        self.unmetered_calls = 0  # calls charged at an estimate because no usage came back
        self.tokens = {"prompt": 0, "candidates": 0, "thoughts": 0}
        self.name = f"gemini-planner:{model}"

    @classmethod
    def from_env(
        cls, *, cost_cap_usd: float = DEFAULT_COST_CAP_USD, ledger: CostBudget | None = None
    ) -> GeminiPlanner:
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
        return cls(client, model, cost_cap_usd=cost_cap_usd, ledger=ledger or session_ledger())

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

    def _charge(self, prompt: int, candidates: int, thoughts: int) -> None:
        """Replace the reservation with what the call cost, here and on the session ledger."""
        self.cost_usd += CostBudget.estimate_call_cost(prompt, candidates, thoughts)
        if self._ledger is not None:
            self._ledger.record_call(prompt, candidates, thoughts)

    def _charge_unmetered(self, digest: str) -> None:
        """Charge a call that may have run with no usage to read: the worst case the
        reservation held, every input token the text could hold plus the whole output
        allowance and the whole thinking budget. It is the same amount, charged once, because
        the hold is released as this is recorded."""
        self.calls += 1
        self.unmetered_calls += 1
        self._charge(_prompt_tokens_upper(digest), MAX_OUTPUT_TOKENS, THINKING_BUDGET)

    def _reserve(self, digest: str) -> float:
        """Refuse the request unless its worst case fits under both caps, and hold it on the
        session ledger. Returns the amount held, which the caller releases."""
        worst = worst_case_cost_usd(digest)
        if self.cost_usd + worst > self._cap:
            raise PlanningError(
                f"the planner's cost cap of ${self._cap:.2f} would be breached: "
                f"${self.cost_usd:.4f} spent and up to ${worst:.4f} for this request"
            )
        if self._ledger is not None:
            allowed, reason = self._ledger.reserve(worst)
            if not allowed:
                spent = self._ledger.report()["run_total_usd"]
                raise PlanningError(
                    f"the session cost cap would be breached ({reason}): ${spent:.4f} spent in "
                    f"this session and up to ${worst:.4f} for this request"
                )
        return worst

    async def plan(self, digest: str, *, round_no: int) -> Plan:
        if not self._idle.is_set():
            raise PlanningError("an earlier model request is still running, so none is started")
        held = self._reserve(digest)
        self._idle.clear()
        try:
            return await self._plan_reserved(digest)
        finally:
            # The actual cost was recorded first, so the ledger never holds neither.
            if self._ledger is not None:
                self._ledger.release(held)

    async def _plan_reserved(self, digest: str) -> Plan:
        try:
            response = await asyncio.to_thread(self._call_in_thread, digest)
        except BaseException:  # a failure or a cancelled wait: the request may still be billed
            self._charge_unmetered(digest)
            raise
        counts = _read_usage(response.usage_metadata)
        if counts is None:  # the call ran and was billed, but its bill cannot be read
            self._charge_unmetered(digest)
        else:
            prompt, candidates, thoughts = counts
            self.calls += 1
            self.tokens["prompt"] += prompt
            self.tokens["candidates"] += candidates
            self.tokens["thoughts"] += thoughts
            self._charge(prompt, candidates, thoughts)
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
