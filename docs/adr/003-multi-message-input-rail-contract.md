# ADR 003: Multi-Message Input Rail Contract

**Date:** 2026-09-09
**Status:** Accepted

## Context

Phase 3C (commits p3c-1, p3c-2) moved input rail evaluation from single-message
("evaluate the last user message only") to per-message ("evaluate every user
message in the conversation"). The motivation is that single-message evaluation
is bypassable: an attacker can embed malicious content in a non-last user turn
in a multi-turn conversation and the rail stack never sees it.

The p3c-2 implementation had a return-shape bug. `run()` returned
`(last_content, status, rail, explain)` where `last_content` was a single string
— the final iteration's `result.content`. The working message list was modified
correctly per-iteration but then discarded. In `main.py`, the gateway applied
`last_content` to every user message via list comprehension on MODIFIED status.

Concrete corruption case: conversation
`[{role:user, content:"SSN 579-34-7285"}, {role:assistant, ...}, {role:user, content:"AAPL revenue?"}]`.
The loop redacted turn 0 into `working[0]["content"] = "<REDACTED...>"` (MODIFIED)
and then saw turn 2 pass clean, setting `last_content = "AAPL revenue?"`. The
gateway then wrote `"AAPL revenue?"` over both user messages. The SSN redaction
was destroyed and turn 0 became a copy of turn 2.

## Decision

`InputRailsAdapter.run()` returns `tuple[list[dict[str, Any]], object, str | None, object]`.
The first element is the full conversation list with per-message transformations
applied in-place on a shallow copy. The gateway consumes the list directly and
assigns `messages = updated_messages` on MODIFIED status. No reconstruction in
the gateway.

On BLOCKED, `run()` returns the original (unmodified) messages list. The gateway
returns 403 and does not forward, so the content does not matter; returning a
list keeps the contract type consistent across all three outcomes.

On PASSED, `run()` returns the working list. Because no message was modified, the
working list is byte-identical to the input. The assignment in the gateway is
idempotent.

Assistant, system, and tool messages are preserved byte-identical. Only
`role == "user"` messages are candidates for rail evaluation.

## Alternatives Considered

**Return single string plus a per-user-index mapping.** The gateway would receive
`(content_map: dict[int, str], status, rail, explain)` and apply each entry
selectively. Rejected. More state to manage in the gateway with no benefit over
returning the list directly.

**Rely on NeMo's built-in multi-message handling.** NeMo's `check_async` accepts
a message list, but its action context only exposes `context["user_message"]`
— which is the last user message from the list. Earlier turns are invisible to
registered actions. This is the root cause of the p3c-1/p3c-2 per-message loop
design: the loop works around NeMo's single-turn context by issuing one
`check_async` call per user message with a single-element message list. Returning
to the single-call design would reintroduce the bypass.

## Consequences

Multi-turn conversations are correctly evaluated for hazards and PII on every
user turn. The redaction applied to turn 0 is preserved regardless of what turns
follow.

Latency scales linearly with user-message count in the request. At Day 2 volumes
(single-digit turns per conversation), this is acceptable. If throughput becomes
a concern in Phase 4, batching multiple user turns into a single `check_async`
call is the upgrade path — but it requires solving the NeMo context exposure
problem noted above.

`ExplainInfo` currently reflects only the last per-message check's audit trail.
Richer aggregation (all rail decisions across all turns surfaced in a single
`ExplainInfo`) is deferred to Phase 4 observability work. The MCP audit surface
on Day 7 will need to accommodate multi-turn trace data.
