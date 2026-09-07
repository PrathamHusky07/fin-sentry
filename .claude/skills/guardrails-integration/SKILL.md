---
name: guardrails-integration
description: "Follow this pattern when adding a new rail to the gateway, modifying an existing rail's failure behavior, or changing how the rail stack emits trace events. Triggers on any work in the gateway rail pipeline including input rails (Llama Prompt Guard 2, Presidio, Llama Guard 3), the retrieval rail (RAGAS Faithfulness before generation), and the output rails (Guardrails AI schema enforcement, post-generation groundedness check). Also triggers when touching the NeMo Guardrails orchestration layer or the OpenTelemetry span emission for rail decisions."
---

# Guardrails integration pattern

Every rail in this platform follows the same lifecycle. If you add or change a rail without following this pattern, the traces will be inconsistent, the fail-open versus fail-closed decision will be implicit instead of explicit, and the dashboard will not know how to render the rail's decision. Follow the pattern.

## The three layers, one more time

The gateway has three distinct rail layers. Know which one you are working in before writing code.

**Input rails** run on the incoming request before anything else happens. The order is Llama Prompt Guard 2 first (cheapest, 20 to 50 ms), then Presidio for PII redaction, then Llama Guard 3 for hazard classification. Each can block or sanitize.

**The retrieval rail** runs between retrieval and generation. It is a single rail. It takes the retrieved chunks and the intended answer path and computes RAGAS Faithfulness against them. If the faithfulness score falls below the configured threshold, the rail blocks or flags the generation before it happens. This is the layer that catches indirect prompt injection buried inside retrieved chunks.

**Output rails** run on the generated response before it returns to the caller. Guardrails AI enforces the response schema and applies the FINRA phrase blocklist. A post-generation groundedness check re-runs Faithfulness on the actual generated response.

If you are unsure which layer a new rail belongs in, ask. The layer choice is not a preference. It follows from what the rail is checking against.

## The five things every rail must implement

Every rail, regardless of layer, exposes the same interface. When you write a new rail, or modify an existing one, it must implement all five.

**One. A `name` attribute.** A short lowercase string, hyphen-separated. Used in the trace event and the dashboard. Must be unique across the platform.

**Two. A `check(request_or_response, context)` method.** Returns a `RailDecision` object with three fields. `outcome` is one of `pass`, `block`, `sanitize`, or `error`. `reason` is a short human-readable string. `details` is a dictionary the dashboard can render, containing whatever numeric or structured evidence the rail produced. For a classifier this is `{"score": 0.87, "threshold": 0.5}`. For Presidio this is `{"pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER"]}`. For Faithfulness this is `{"faithfulness": 0.42, "unsupported_claims": ["..."]}`.

**Three. An explicit `on_failure` configuration.** Every rail declares whether it fails closed or fails open when the rail's own machinery fails (model unreachable, library exception). The default for the finance domain is fail-closed. Fail-open is allowed per-rail with an explicit configuration entry. The `RailDecision.outcome` for a failure is `error`, not `pass` or `block`. The fail-open versus fail-closed logic decides what the caller does with the `error` outcome.

**Four. An OpenTelemetry span.** Every rail emits its own span with `rail.name`, `rail.layer` (`input`, `retrieval`, or `output`), `rail.outcome`, `rail.latency_ms`, and any details as span attributes. The span is a child of the request-level trace span. The convention is `rail.<name>.check` for the span name.

**Five. A registration in the NeMo Guardrails config.** Every rail is wired into the `config.yml` for its layer. Never bypass NeMo Guardrails and call a rail directly. If a rail runs outside NeMo, its decisions do not flow through the same audit surface as everything else and the dashboard breaks.

## The trace event contract

When a request finishes flowing through the gateway, the emitted trace event has a `rail_decisions` field. It is a list of `RailDecision` objects in the order they ran, with the layer name attached. The dashboard and the MCP server both read this field directly. Do not invent a new shape for the same data. If you find a case where the shape is not enough, add a field to `RailDecision.details` rather than restructuring the top level.

## The pattern for adding a new rail

Follow this order.

1. Write the rail class. Implement `check()`, declare `name` and default `on_failure`. Keep the class in `finsentry/rails/<layer>/`.
2. Write the tests. A rail without tests does not go into the config. Test three cases minimum. A clear pass. A clear block. A machinery failure that triggers the `on_failure` path.
3. Wire the OpenTelemetry span. Verify a test run produces the span with the expected attributes by inspecting the OTel collector output.
4. Register the rail in the NeMo Guardrails `config.yml` for its layer. Include the ordering. Cheap rails run first.
5. Update the frontend if the dashboard needs to render a new detail shape. Check the Judge Panel modal renders it correctly.
6. Add one line to the `RAILS.md` inventory at the repo root. Name, layer, purpose, latency budget.

## When you touch fail-open versus fail-closed

The decision is per-rail and is stored in `config/rails.yml`. Never hardcode fail-open or fail-closed behavior inside the rail class itself. The class returns an `error` outcome. The gateway-level policy decides what to do with it. This separation is what lets the same rail behave one way in the finance-domain configuration and a different way in a lower-stakes deployment configuration.

When you change a rail's default, update `config/rails.yml`, update the tests to cover both behaviors, and add a one-line note to `RAILS.md`.

## Verification checklist before you say a rail is done

Run through all six. Do not skip any.

1. Unit tests pass for pass, block, and error paths.
2. A live gateway request that trips the rail produces the correct `RailDecision` in the trace event.
3. The OpenTelemetry span appears in the collector output with the expected attributes.
4. The dashboard renders the rail's `details` correctly in the Judge Panel modal.
5. The MCP server's `explain_guardrail_decision` tool returns the rail's decision when queried for the request ID.
6. The latency of the rail measured over a hundred requests fits inside the budget declared in `RAILS.md`. If it does not, either optimize or update the budget with a reason.

If any of the six fails, the rail is not done. Do not move on to the next task with a rail in this state.
