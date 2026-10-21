/**
 * The Fin-Sentry system model behind the landing topology and the
 * architecture page. Every statement here was read from the backend source
 * (not run) and names the module it came from. Where the source does not
 * back a claim, the claim is absent or says so. Notable corrections to
 * older project copy, all verified in source:
 *   - The flash judge is gemini-3.6-flash, hosted (Vertex or AI Studio).
 *   - The frontier judge is a hosted Gemini rubric judge ("gemini-rubric").
 *     No frontier model runs locally in the default configuration. HHEM
 *     is implemented but disabled, Lynx and Prometheus have no adapter.
 *   - Calibration covers gemini-rubric only and is one manual run saved to
 *     disk, not a scheduled monitor and not a request-path step.
 *   - NeMo Guardrails orchestrates the input rails only.
 */

export type Plane = "request" | "stream" | "evaluation" | "evidence";

export type NodeId =
  | "client"
  | "gateway"
  | "input"
  | "retrieval"
  | "generation"
  | "output"
  | "response"
  | "stream"
  | "flash"
  | "sampler"
  | "frontier"
  | "calibration"
  | "store"
  | "investigation"
  | "mcp";

export interface ArchNode {
  id: NodeId;
  plane: Plane;
  label: string;
  /** Short qualifier shown under the label inside the node. */
  sub: string;
  /** What this stage does, in one or two sentences. */
  summary: string;
  /** Why it exists: the failure it prevents or the question it answers. */
  why: string;
  /** Backend module the statement was verified against. */
  source: string;
}

export const PLANE_LABEL: Record<Plane, string> = {
  request: "Request path",
  stream: "Event stream",
  evaluation: "Evaluation plane",
  evidence: "Evidence",
};

export const PLANE_TIMING: Record<Plane, string> = {
  request: "Synchronous",
  stream: "Boundary",
  evaluation: "Asynchronous",
  evidence: "Persisted",
};

export const NODES: Record<NodeId, ArchNode> = {
  client: {
    id: "client",
    plane: "request",
    label: "Client",
    sub: "a question about a filing",
    summary:
      "Asks a question about one of ten SEC filers. The corpus is 10-K, 10-Q and 8-K filings for those ten companies.",
    why: "This is the only synchronous caller. Every number the platform reports starts as one of these requests.",
    source: "finsentry/gateway/main.py",
  },
  gateway: {
    id: "gateway",
    plane: "request",
    label: "Gateway",
    sub: "the single front door",
    summary:
      "Owns the request from arrival to response, and emits one event per request when the decision is made.",
    why: "A single front door means every request is guarded, bounded and recorded the same way, whatever model sits behind it.",
    source: "finsentry/gateway/main.py",
  },
  input: {
    id: "input",
    plane: "request",
    label: "Input rails",
    sub: "injection, PII, hazard checks",
    summary:
      "NeMo Guardrails runs three checks: Prompt Guard 2 for prompt injection, Presidio to redact PII, and Llama Guard 3 for the hazard taxonomy.",
    why: "Hostile or unsafe input should never reach retrieval or the model. These rails fail closed, so a rail that errors stops the request instead of waving it through.",
    source: "finsentry/gateway/rails.py, finsentry/rails/input/",
  },
  retrieval: {
    id: "retrieval",
    plane: "request",
    label: "Retrieval",
    sub: "vector search, chunk checks",
    summary:
      "Embeds the query, pulls the closest filing chunks from pgvector, then checks each chunk for source trust, injection and PII.",
    why: "Retrieved text is untrusted input too. A bad chunk is dropped before it reaches the prompt. If no chunk survives, the request stops with no trustworthy sources.",
    source: "finsentry/rails/retrieval/rail.py",
  },
  generation: {
    id: "generation",
    plane: "request",
    label: "Generation",
    sub: "local model, bounded call",
    summary:
      "A local llama3.1:8b model answers in JSON mode. The call has a 20 second budget, a 15 second cap per attempt, and a circuit breaker.",
    why: "A slow or failing model must not hold the gateway open. After five failures the breaker opens for 30 seconds and callers get an immediate 503. The breaker guards this call only.",
    source: "finsentry/gateway/main.py",
  },
  output: {
    id: "output",
    plane: "request",
    label: "Output rails",
    sub: "schema, citations, faithfulness",
    summary:
      "Checks the model’s answer before it is returned: output schema and citations, regulated phrases, and a request-time faithfulness score when Gemini is enabled.",
    why: "Valid JSON is not a grounded answer. These rails reject malformed output, citations to chunks that were never retrieved, and answers scored below 0.7 for faithfulness.",
    source: "finsentry/rails/output/, finsentry/gateway/main.py",
  },
  response: {
    id: "response",
    plane: "request",
    label: "Response",
    sub: "an answer or a named block",
    summary:
      "Returns an answer with citations, or a block that names the rail that stopped it.",
    why: "A block is a recorded result, not a silent failure. Its reason and rail are persisted so the execution can be investigated later.",
    source: "finsentry/gateway/main.py",
  },
  stream: {
    id: "stream",
    plane: "stream",
    label: "Event stream",
    sub: "Redpanda: responses, flash verdicts, frontier verdicts",
    summary:
      "After the decision, the gateway publishes one event and does not wait for delivery. Judges read it from the stream and write their verdicts back to it.",
    why: "Evaluation is slow and can fail, so it stays off the request path. The tradeoff is at-most-once delivery: an event can be lost, and the platform treats its evaluation data as telemetry, not a ledger.",
    source: "finsentry/events/producer.py, docs/adr/006",
  },
  flash: {
    id: "flash",
    plane: "evaluation",
    label: "Flash judge",
    sub: "gemini-3.6-flash, every answer",
    summary:
      "A consumer scores every successful answer on faithfulness, answer relevance and context relevance with a hosted Gemini model.",
    why: "Broad, inexpensive coverage. Every delivered answer gets a verdict. A verdict can be partial when one metric times out, and the platform keeps that distinction.",
    source: "finsentry/judges/flash_judge.py",
  },
  sampler: {
    id: "sampler",
    plane: "evaluation",
    label: "Deterministic sampler",
    sub: "1 in 10 reviewed",
    summary:
      "Selects about one trace in ten for frontier review by hashing the trace id.",
    why: "The decision depends only on the trace id, so a retry or a replay never changes whether a trace is reviewed. The rate is fixed at one in ten with no backpressure control.",
    source: "finsentry/frontier/sampling.py",
  },
  frontier: {
    id: "frontier",
    plane: "evaluation",
    label: "Frontier judge",
    sub: "a second opinion, hosted Gemini",
    summary:
      "A hosted Gemini judge scores sampled answers against a rubric and records its reasoning and the chunks it relied on.",
    why: "A slower second opinion on a sample. It is the judge that caught the Amazon net income answer the flash tier scored as fully faithful. It runs on hosted Gemini, not locally.",
    source: "finsentry/frontier/adapters/gemini_rubric_adapter.py",
  },
  calibration: {
    id: "calibration",
    plane: "evaluation",
    label: "Calibration",
    sub: "measured against labeled data",
    summary:
      "Compares the frontier judge with labels from the FinQA hallucination benchmark using Cohen’s kappa, then reads the result against drift thresholds.",
    why: "A judge is a model that can be wrong. Calibration reports on the judge, not on any request. Today it is one manual canary run saved to disk, so it is a last known reading and not a live monitor.",
    source: "finsentry/reliability/, finsentry/mcp/tools/drift.py",
  },
  store: {
    id: "store",
    plane: "evidence",
    label: "RisingWave",
    sub: "live views over the event stream",
    summary:
      "Reads the three Redpanda topics as sources and maintains materialized views for throughput, latency, tokens and cost.",
    why: "Persisted events and verdicts are the evidence. A streaming database keeps the views current without a batch job, and only the dashboard service queries it.",
    source: "infra/risingwave/init.sql, finsentry/dashboard/app.py",
  },
  investigation: {
    id: "investigation",
    plane: "evidence",
    label: "Investigations",
    sub: "one row per execution",
    summary:
      "Every persisted execution is one row with its rail outcome, retrieved chunks, scores and reasoning.",
    why: "Summaries can hide the one case that matters. This surface never groups, samples or deduplicates.",
    source: "finsentry/events/trace_api.py",
  },
  mcp: {
    id: "mcp",
    plane: "evidence",
    label: "MCP server",
    sub: "nine read tools",
    summary:
      "Exposes nine read tools over the same evidence: failing traces, guardrail decisions, judge scores, injection search, the drift report, trace search, trace detail and two Red Team execution reads.",
    why: "Lets an engineer’s tooling ask the platform why something failed, with OpenTelemetry instrumentation. A red team scenario tool is not registered yet.",
    source: "finsentry/mcp/server.py",
  },
};

export type EdgeKind = "sync" | "async" | "measure";

export interface ArchEdge {
  from: NodeId;
  to: NodeId;
  kind: EdgeKind;
  /** Reads along the arrow, from the source to the target. */
  label?: string;
}

export const EDGES: ArchEdge[] = [
  { from: "client", to: "gateway", kind: "sync" },
  { from: "gateway", to: "input", kind: "sync" },
  { from: "input", to: "retrieval", kind: "sync" },
  { from: "retrieval", to: "generation", kind: "sync" },
  { from: "generation", to: "output", kind: "sync" },
  { from: "output", to: "response", kind: "sync" },
  { from: "gateway", to: "stream", kind: "async" },
  { from: "stream", to: "flash", kind: "async" },
  { from: "stream", to: "sampler", kind: "async" },
  { from: "sampler", to: "frontier", kind: "async" },
  {
    from: "frontier",
    to: "calibration",
    kind: "measure",
    label: "measured by",
  },
  { from: "stream", to: "store", kind: "async" },
  { from: "flash", to: "store", kind: "async" },
  { from: "frontier", to: "store", kind: "async" },
  { from: "store", to: "investigation", kind: "async" },
  { from: "store", to: "mcp", kind: "async" },
];

export const REQUEST_PATH: NodeId[] = [
  "client",
  "gateway",
  "input",
  "retrieval",
  "generation",
  "output",
  "response",
];

export const PLANE_NODES: Record<Plane, NodeId[]> = {
  request: REQUEST_PATH,
  stream: ["stream"],
  evaluation: ["flash", "sampler", "frontier", "calibration"],
  evidence: ["store", "investigation", "mcp"],
};

/** DOM id of a request-path stage. The wide pipeline and the narrow outline
 * are both in the page, so each has its own id and a link picks the one that
 * is visible. */
export function stageAnchor(
  id: NodeId,
  variant: "wide" | "outline" = "wide",
): string {
  return variant === "wide" ? `stage-${id}` : `stage-${id}-outline`;
}

/** Nodes directly connected to `id` by any edge, plus `id` itself. */
export function relatedNodes(id: NodeId): Set<NodeId> {
  const related = new Set<NodeId>([id]);
  for (const edge of EDGES) {
    if (edge.from === id) related.add(edge.to);
    if (edge.to === id) related.add(edge.from);
  }
  return related;
}
