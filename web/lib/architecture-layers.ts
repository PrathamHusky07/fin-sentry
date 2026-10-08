import { stageAnchor, type NodeId } from "@/lib/architecture-data";

/**
 * Prose for the four architecture layers. Every statement was read from the
 * backend source, not checked by running the system. The `outline` is the
 * same story as the diagram in plain list form, shown on screens too narrow
 * for a diagram.
 */
export interface Reason {
  term: string;
  body: string;
}

export interface OutlineLane {
  caption: string;
  steps: { label: string; sub: string; anchor?: string }[];
}

export interface Layer {
  id:
    | "request-path"
    | "evaluation-plane"
    | "event-infrastructure"
    | "operational-interface";
  name: string;
  question: string;
  intro: string;
  outline: OutlineLane[];
  reasons: Reason[];
}

const A = (id: NodeId) => stageAnchor(id, "outline");

export const LAYERS: Layer[] = [
  {
    id: "request-path",
    name: "Request path",
    question: "What happens between a question and its answer?",
    intro:
      "This is the only synchronous part of the system. A request passes through guardrails on the way in, retrieval, one bounded model call, and guardrails on the way out. Anything that stops it leaves a recorded reason.",
    outline: [
      {
        caption:
          "One request, answered or blocked before anything is evaluated",
        steps: [
          {
            anchor: A("client"),
            label: "Client",
            sub: "asks a question about a filing",
          },
          {
            anchor: A("gateway"),
            label: "Gateway",
            sub: "the single front door",
          },
          {
            anchor: A("input"),
            label: "Input rails",
            sub: "prompt injection, PII, hazard taxonomy. A failing rail blocks the request.",
          },
          {
            anchor: A("retrieval"),
            label: "Retrieval",
            sub: "vector search, then a check on every chunk for source trust, injection and PII",
          },
          {
            anchor: A("generation"),
            label: "Generation",
            sub: "a local model, with a 20 second budget, 15 seconds per attempt and a circuit breaker",
          },
          {
            anchor: A("output"),
            label: "Output rails",
            sub: "schema and citations, regulated phrases, then a faithfulness check below 0.7",
          },
          {
            anchor: A("response"),
            label: "Response",
            sub: "an answer or a named block",
          },
        ],
      },
    ],
    reasons: [
      {
        term: "Why input rails run first and fail closed",
        body: "Hostile input should never reach retrieval or the model. The input, schema and phrase rails fail closed: if a rail errors, the request is blocked. The faithfulness rail fails open, so a Gemini outage degrades evaluation without stopping answers.",
      },
      {
        term: "Why retrieval has its own rail",
        body: "Retrieved chunks are untrusted text. Each is checked for source trust, injection and PII before it reaches the prompt. If no chunk survives, the result is a recorded block, not a guess.",
      },
      {
        term: "Why NeMo only owns the input side",
        body: "NeMo Guardrails runs the input rails as Colang flows with no model of its own. The retrieval and output rails are plain Python that the gateway calls directly.",
      },
      {
        term: "Why the model call is bounded",
        body: "A 20 second budget and a breaker that opens after five failures keep a dead model from holding the gateway open. The budget covers the model call, not the whole request.",
      },
    ],
  },
  {
    id: "evaluation-plane",
    name: "Evaluation plane",
    question: "How do we know the answer was any good?",
    intro:
      "Evaluation starts after the response decision and never delays it. Two judges look at delivered answers, and a separate calibration step asks how far the frontier judge can be trusted.",
    outline: [
      {
        caption: "Every delivered answer",
        steps: [
          { label: "Response event", sub: "published by the gateway" },
          {
            label: "Flash judge",
            sub: "gemini-3.6-flash scores faithfulness, answer relevance and context relevance",
          },
          { label: "Flash verdict", sub: "written back to the event stream" },
        ],
      },
      {
        caption: "One trace in ten, chosen by a hash of the trace id",
        steps: [
          {
            label: "Deterministic sampler",
            sub: "keeps about one trace in ten",
          },
          {
            label: "Frontier judge",
            sub: "a hosted Gemini rubric judge records a score, its reasoning and the chunks it used",
          },
          {
            label: "Frontier verdict",
            sub: "written back to the event stream",
          },
        ],
      },
      {
        caption: "Calibration measures the judge, not any request",
        steps: [
          { label: "Labeled benchmark", sub: "FinQA hallucination rows" },
          { label: "Frontier judge", sub: "scores the labeled rows" },
          { label: "Cohen’s kappa", sub: "agreement with the labels" },
          { label: "Drift thresholds", sub: "enter at 0.43, recover at 0.54" },
        ],
      },
    ],
    reasons: [
      {
        term: "Why evaluation is off the request path",
        body: "Judging is slow and can fail. Keeping it behind an event stream means a judge outage costs coverage, never availability.",
      },
      {
        term: "Why there are two judge tiers",
        body: "The flash judge is inexpensive enough to score every delivered answer. The frontier judge is slower and sees a sample. Two tiers make disagreement measurable, and one real disagreement is on record.",
      },
      {
        term: "Why sampling is deterministic",
        body: "The decision depends only on the trace id, so a retry or a replay never changes whether a trace is reviewed. The cost is a fixed rate with no backpressure control.",
      },
      {
        term: "Why calibration exists",
        body: "A judge is a model, and it can be wrong. Calibration puts a number on that. Today it is one manual canary run saved to disk and it covers the frontier judge only, so it is a last known reading, not a live monitor.",
      },
    ],
  },
  {
    id: "event-infrastructure",
    name: "Event infrastructure",
    question: "How does data get from a request to a screen?",
    intro:
      "The gateway only writes to a log. Everything else, including the dashboard, is built from that log, so no screen depends on the request path being healthy.",
    outline: [
      {
        caption: "Write side: events and verdicts go in",
        steps: [
          { label: "Gateway", sub: "publishes one event and does not wait" },
          {
            label: "Redpanda",
            sub: "three topics: responses, flash verdicts, frontier verdicts",
          },
          {
            label: "Consumers",
            sub: "the flash and frontier judges run as separate processes",
          },
          {
            label: "Verdict topics",
            sub: "verdicts are written back to Redpanda",
          },
        ],
      },
      {
        caption: "Read side: views come out",
        steps: [
          {
            label: "RisingWave",
            sub: "reads all three topics and keeps eight materialized views",
          },
          { label: "Dashboard service", sub: "the only RisingWave client" },
          {
            label: "Gateway endpoints",
            sub: "traces and the stream, polled every 3 seconds",
          },
          {
            label: "Browser",
            sub: "receives full-state snapshots over Server-Sent Events",
          },
        ],
      },
    ],
    reasons: [
      {
        term: "Why Redpanda sits between the gateway and everything else",
        body: "A log lets judges restart, lag or be added without touching the request path. The gateway sends each event once and does not wait, so delivery is at-most-once and an event can be lost.",
      },
      {
        term: "Why RisingWave builds the views",
        body: "Throughput, latency, token and cost views need to stay current as events arrive. RisingWave defines them as materialized views over the topics, so there is no batch job to schedule or fall behind.",
      },
      {
        term: "Why the browser gets snapshots, not events",
        body: "The gateway never connects to RisingWave. A poller asks the dashboard service for a snapshot every three seconds and relays the latest one. Each message is full current state, so a reconnect just waits for the next one.",
      },
      {
        term: "Why calibration is the exception",
        body: "The calibration reading is not in RisingWave. The dashboard service reads a JSON file from disk, which is why the page labels it with the time it was written.",
      },
    ],
  },
  {
    id: "operational-interface",
    name: "MCP & operational interface",
    question:
      "How does an engineer or an agent ask the platform what went wrong?",
    intro:
      "The same persisted evidence is exposed twice: through an MCP server for tools and agents, and as screens for people. Both read what was recorded and neither changes it. The read tools exist today. The tool that would run Red Team scenarios is not registered yet.",
    outline: [
      {
        caption: "Read paths over the persisted evidence",
        steps: [
          {
            label: "Persisted evidence",
            sub: "events and verdicts in RisingWave",
          },
          {
            label: "Screens",
            sub: "Overview, Live Operations and Investigations",
          },
          {
            label: "MCP server",
            sub: "five read tools: failing traces, guardrail decisions, judge scores, injection search and the drift report",
          },
          { label: "Engineer or agent", sub: "asks why a trace failed" },
        ],
      },
      {
        caption: "Adversarial testing: not built",
        steps: [
          { label: "Scenario registry", sub: "does not exist yet" },
          { label: "Scenario tool", sub: "an MCP tool that is not registered" },
          {
            label: "Red Team route",
            sub: "shows this status instead of a mock",
          },
        ],
      },
    ],
    reasons: [
      {
        term: "Why MCP",
        body: "An MCP server gives investigation tools a typed interface over the same evidence, so an engineer or an agent can ask for failing traces, a guardrail decision or the drift report without learning the schema.",
      },
      {
        term: "Why the gateway emits OpenTelemetry spans",
        body: "Each request stage and each rail records a span, with the trace id as an attribute. The default exporter is off, so spans exist but are not shipped anywhere until one is configured.",
      },
      {
        term: "Why Red Team is shown as not built",
        body: "There is no stored scenario registry yet, and the MCP tool that would fire scenarios is deliberately unregistered. A console over nothing would be a mock, so the route says what is missing.",
      },
    ],
  },
];
