"""
output_rails executor: calls the real output rails on a fixed model reply, in the
order the gateway's rag handler runs them (schema, then regulated phrases, then
faithfulness), and stops at the first block.

The gateway route cannot be handed a model reply, so the reply is a controlled
string. Faithfulness is the only step that spends Gemini calls, and it runs only
for judge_assisted scenarios. Before any miss is believed, the harness verifies its
own payload really had the property under test.
"""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

from finsentry.rails.base import RailDecision
from finsentry.rails.output.schema import RagAnswerResponse
from finsentry.redteam.classify import Observation
from finsentry.redteam.deps import Deps
from finsentry.redteam.models import OutputRailsInput, OutputRailsScenario

_FAITHFULNESS_BUDGET_SECONDS = 90.0


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def verify_payload(data: OutputRailsInput) -> bool:
    """Ground truth about the harness's own payload, without asking the rail under test."""
    check = data.payload_check
    chunk_text = {c.chunk_id: c.text for c in data.retrieved}
    try:
        parsed = RagAnswerResponse.model_validate_json(data.raw_output)
    except ValueError:
        return False
    if check.kind == "citation_id_unretrieved":
        return any(c.chunk_id not in chunk_text for c in parsed.citations)
    if check.kind == "quote_not_in_cited_chunk":
        return any(
            c.chunk_id in chunk_text and _norm(c.quote) not in _norm(chunk_text[c.chunk_id])
            for c in parsed.citations
        )
    value = _norm(check.value or "")
    if check.kind == "answer_contains":
        return value in _norm(parsed.answer)
    return value in _norm(parsed.answer) and all(value not in _norm(t) for t in chunk_text.values())


def _decision(d: RailDecision) -> dict[str, object]:
    return {"outcome": d.outcome, "reason": d.reason}


async def run_output_rails(scenario: OutputRailsScenario, deps: Deps) -> Observation:
    if deps.schema_rail is None or deps.phrase_rail is None:
        return Observation(summary="", unavailable_reason="The output rails are not loaded.")
    data = scenario.input
    verified = verify_payload(data)
    evidence: dict[str, object] = {"payload_verified": verified}
    obs = partial(Observation, evidence=evidence, payload_verified=verified)

    schema = deps.schema_rail.check(data.raw_output, {c.chunk_id for c in data.retrieved})
    evidence["schema_decision"] = _decision(schema)
    if schema.outcome == "block":
        return obs(
            summary=f"The schema rail blocked the reply: {schema.reason}.",
            defense_acted=True,
            acting_layer="schema-enforcement",
            acting_check=schema.reason,
        )
    parsed: RagAnswerResponse = schema.details["parsed"]

    phrase = deps.phrase_rail.check(parsed.answer)
    evidence["phrase_decision"] = _decision(phrase)
    if phrase.outcome == "block":
        return obs(
            summary="The regulated-phrase rail blocked the answer.",
            defense_acted=True,
            acting_layer="regulated-phrases",
            acting_check=phrase.reason,
        )
    if scenario.mode != "judge_assisted":
        return obs(
            summary="The reply passed the schema and regulated-phrase rails.", attack_passed=True
        )
    return await _run_faithfulness(deps, parsed, data, obs, evidence)


async def _run_faithfulness(
    deps: Deps,
    parsed: RagAnswerResponse,
    data: OutputRailsInput,
    obs: partial[Observation],
    evidence: dict[str, object],
) -> Observation:
    rail = deps.faithfulness_rail
    if rail is None:
        return obs(summary="", unavailable_reason="The faithfulness rail is not loaded.")
    chunks = [SimpleNamespace(chunk_id=c.chunk_id, text=c.text) for c in data.retrieved]
    decision = await rail.check(parsed.answer, chunks, total_budget=_FAITHFULNESS_BUDGET_SECONDS)
    details = decision.details
    status = str(details.get("faithfulness_status", ""))
    cost = details.get("cost")
    cost_usd = float(cost["run_total_usd"]) if isinstance(cost, dict) else 0.0
    calls = int(details.get("gemini_calls", 0))
    evidence["faithfulness_decision"] = {
        "outcome": decision.outcome,
        "reason": decision.reason,
        "status": status,
        "score": details.get("score"),
        "threshold": details.get("threshold"),
        "supported_claim_count": len(details.get("supported_claims", [])),
        "unsupported_claim_count": len(details.get("unsupported_claims", [])),
    }
    spend = partial(obs, gemini_calls=calls, cost_usd=cost_usd)
    if status.startswith("skipped"):
        return spend(
            summary="The faithfulness judge did not return a verdict.",
            unavailable_reason=f"The faithfulness judge could not run ({status}).",
        )
    if decision.outcome == "block":
        return spend(
            summary="The faithfulness rail blocked the answer as unsupported by the context.",
            defense_acted=True,
            acting_layer="faithfulness",
            acting_check=decision.reason,
        )
    return spend(
        summary="The faithfulness rail judged the answer supported by the context.",
        attack_passed=True,
    )
