import type { Metadata } from "next";
import Link from "next/link";
import { FlowChain, type ChainStep } from "@/components/flow-chain";

export const metadata: Metadata = {
  title: "Architecture — Fin-Sentry",
};

interface Reason {
  term: string;
  body: string;
}

interface Lane {
  caption: string;
  edge: "sync" | "async";
  steps: ChainStep[];
}

interface Layer {
  id: string;
  number: string;
  name: string;
  question: string;
  intro: string;
  lanes: Lane[];
  reasons: Reason[];
  sources: string;
}

// Every statement was read from the backend source files named in each
// layer’s `sources` line. Nothing here was checked by running the system.
const LAYERS: Layer[] = [
  {
    id: "request-path",
    number: "01",
    name: "Request path",
    question: "What happens between a question and its answer?",
    intro:
      "This is the only synchronous part of the system. A request passes through guardrails on the way in, retrieval, one bounded model call, and guardrails on the way out. Anything that stops it leaves a recorded reason.",
    lanes: [
      {
        caption:
          "One request, answered or blocked before anything is evaluated",
        edge: "sync",
        steps: [
          { label: "Client", sub: "POST /v1/rag/query", tone: "request" },
          { label: "Gateway", sub: "FastAPI", tone: "request" },
          {
            label: "NeMo Guardrails",
            sub: "Input rails",
            tone: "request",
            chips: [
              "Prompt injection: Prompt Guard 2",
              "PII: Presidio redacts",
              "Hazard taxonomy: Llama Guard 3",
            ],
          },
          {
            label: "Retrieval",
            sub: "pgvector, then a rail per chunk",
            tone: "request",
            chips: ["Source trust", "Injection scan", "PII redaction"],
          },
          {
            label: "Ollama",
            sub: "llama3.1:8b, local",
            tone: "request",
            chips: ["20 s budget", "15 s per attempt", "Circuit breaker"],
          },
          {
            label: "Output rails",
            sub: "Python, called by the gateway",
            tone: "request",
            chips: [
              "Schema and citations",
              "Regulated phrases",
              "Faithfulness below 0.7",
            ],
          },
          {
            label: "Response",
            sub: "Answer or a named block",
            tone: "request",
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
    sources:
      "finsentry/gateway/main.py, finsentry/gateway/rails.py, finsentry/rails/",
  },
  {
    id: "evaluation-plane",
    number: "02",
    name: "Evaluation plane",
    question: "How do we know the answer was any good?",
    intro:
      "Evaluation starts after the response decision and never delays it. Two judges look at delivered answers, and a separate calibration step asks how far the frontier judge can be trusted.",
    lanes: [
      {
        caption: "Every delivered answer",
        edge: "async",
        steps: [
          {
            label: "Response event",
            sub: "rag-responses topic",
            tone: "stream",
          },
          {
            label: "Flash judge",
            sub: "gemini-3.6-flash, hosted",
            tone: "evaluation",
            chips: ["Faithfulness", "Answer relevance", "Context relevance"],
          },
          {
            label: "Flash verdict",
            sub: "judge-verdicts topic",
            tone: "stream",
          },
        ],
      },
      {
        caption: "One trace in ten, chosen by a hash of the trace id",
        edge: "async",
        steps: [
          {
            label: "Response event",
            sub: "rag-responses topic",
            tone: "stream",
          },
          {
            label: "Sampler",
            sub: "sha256(trace id) mod 10",
            tone: "evaluation",
          },
          {
            label: "Frontier judge",
            sub: "gemini-rubric, hosted",
            tone: "evaluation",
            chips: ["Rubric score", "Written reasoning", "Cited chunks"],
          },
          {
            label: "Frontier verdict",
            sub: "rag-frontier-verdicts topic",
            tone: "stream",
          },
        ],
      },
      {
        caption: "Calibration reads on the judge, not on any request",
        edge: "async",
        steps: [
          {
            label: "Labeled benchmark",
            sub: "FinQA hallucination rows",
            tone: "evidence",
          },
          {
            label: "Frontier judge",
            sub: "scores the rows",
            tone: "evaluation",
          },
          {
            label: "Cohen’s kappa",
            sub: "agreement with the labels",
            tone: "evaluation",
          },
          {
            label: "Drift thresholds",
            sub: "enter at 0.43, recover at 0.54",
            tone: "evaluation",
            dashed: true,
          },
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
    sources:
      "finsentry/judges/flash_judge.py, finsentry/frontier/, finsentry/reliability/, finsentry/mcp/tools/drift.py",
  },
  {
    id: "event-infrastructure",
    number: "03",
    name: "Event infrastructure",
    question: "How does data get from a request to a screen?",
    intro:
      "The gateway only writes to a log. Everything else, including the dashboard, is built from that log, so no screen depends on the request path being healthy.",
    lanes: [
      {
        caption: "Write side: events and verdicts",
        edge: "async",
        steps: [
          { label: "Gateway", sub: "publishes, never waits", tone: "request" },
          {
            label: "Redpanda",
            sub: "Three topics",
            tone: "stream",
            chips: ["rag-responses", "judge-verdicts", "rag-frontier-verdicts"],
          },
          {
            label: "Consumers",
            sub: "Run as separate processes",
            tone: "evaluation",
            chips: ["Flash judge consumer", "Frontier consumer"],
          },
          {
            label: "Verdict topics",
            sub: "Written back to Redpanda",
            tone: "stream",
          },
        ],
      },
      {
        caption: "Read side: from topics to the browser",
        edge: "async",
        steps: [
          {
            label: "RisingWave",
            sub: "Reads all three topics as sources",
            tone: "evidence",
            chips: ["Eight materialized views"],
          },
          {
            label: "Dashboard service",
            sub: "The only RisingWave client",
            tone: "evidence",
          },
          {
            label: "Gateway proxies",
            sub: "/ops/traces, /ops/stream",
            tone: "request",
            chips: ["Snapshot poll every 3 s"],
          },
          { label: "Browser", sub: "Server-Sent Events", tone: "request" },
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
    sources:
      "finsentry/events/, finsentry/consumer/, infra/risingwave/init.sql, finsentry/dashboard/app.py, finsentry/gateway/metrics_poller.py",
  },
  {
    id: "operational-interface",
    number: "04",
    name: "Operational interface",
    question: "How does an engineer ask the platform what went wrong?",
    intro:
      "The same persisted evidence is exposed twice: as screens for people and as an MCP server for tools. Both read what was recorded and neither changes it.",
    lanes: [
      {
        caption: "Investigation tooling",
        edge: "async",
        steps: [
          {
            label: "Persisted evidence",
            sub: "Events and verdicts in RisingWave",
            tone: "evidence",
          },
          {
            label: "MCP server",
            sub: "Five read tools, OpenTelemetry instrumented",
            tone: "evidence",
            chips: [
              "get_failing_traces",
              "explain_guardrail_decision",
              "get_judge_scores",
              "search_prompt_injections",
              "get_drift_report",
            ],
          },
          {
            label: "Engineer or agent",
            sub: "Asks why a trace failed",
            tone: "muted",
          },
        ],
      },
      {
        caption: "Adversarial testing: not built",
        edge: "async",
        steps: [
          {
            label: "Scenario registry",
            sub: "Does not exist yet",
            tone: "muted",
            dashed: true,
          },
          {
            label: "run_red_team_scenario",
            sub: "MCP tool, not registered",
            tone: "muted",
            dashed: true,
          },
          {
            label: "Red Team route",
            sub: "Shows this status, not a mock",
            tone: "muted",
            dashed: true,
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
    sources:
      "finsentry/mcp/server.py, finsentry/mcp/tools/, finsentry/observability/tracing.py",
  },
];

export default function ArchitecturePage() {
  return (
    <div className="flex flex-col">
      <header className="border-border relative isolate overflow-hidden border-b">
        <div
          aria-hidden="true"
          className="field-glow pointer-events-none absolute inset-0 -z-10"
        />
        <div
          aria-hidden="true"
          className="field-grid pointer-events-none absolute inset-0 -z-10"
        />
        <div className="mx-auto w-full max-w-7xl px-4 pt-16 pb-14 sm:px-8 sm:pt-20">
          <p className="eyebrow rise">Architecture</p>
          <h1 className="text-text-primary rise rise-2 mt-5 max-w-4xl text-5xl leading-[1.05] font-semibold tracking-tight text-balance sm:text-6xl">
            How Fin-Sentry is built, and{" "}
            <span className="display-accent text-signal">why.</span>
          </h1>
          <p className="text-text-secondary rise rise-3 mt-6 max-w-2xl text-lg leading-relaxed text-pretty">
            Four layers, from the request that arrives to the tools an engineer
            uses afterward. Each layer names what it does, why it exists, and
            where in the code the claim can be checked.
          </p>

          <nav aria-label="Architecture layers" className="mt-12">
            <ol className="border-border-strong grid border-t sm:grid-cols-2 lg:grid-cols-4">
              {LAYERS.map((layer) => (
                <li
                  key={layer.id}
                  className="border-border border-b lg:border-b-0 lg:border-r lg:last:border-r-0"
                >
                  <a
                    href={`#${layer.id}`}
                    className="hover:bg-surface/60 flex min-h-11 flex-col gap-1.5 px-1 py-5 transition-colors lg:px-5 lg:first:pl-0"
                  >
                    <span className="text-text-tertiary font-mono text-sm tabular-nums">
                      {layer.number}
                    </span>
                    <span className="text-text-primary text-lg font-semibold tracking-tight">
                      {layer.name}
                    </span>
                    <span className="text-text-secondary text-sm leading-snug">
                      {layer.question}
                    </span>
                  </a>
                </li>
              ))}
            </ol>
          </nav>
        </div>
      </header>

      {LAYERS.map((layer) => (
        <section
          key={layer.id}
          id={layer.id}
          aria-labelledby={`${layer.id}-heading`}
          className="border-border border-b"
        >
          <div className="mx-auto w-full max-w-7xl px-4 py-20 sm:px-8">
            <div className="grid gap-6 lg:grid-cols-[8rem_1fr] lg:gap-10">
              <p
                aria-hidden="true"
                className="display-accent text-text-tertiary/50 text-7xl leading-none lg:text-8xl"
              >
                {layer.number}
              </p>
              <div className="max-w-3xl">
                <h2
                  id={`${layer.id}-heading`}
                  className="text-text-primary text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
                >
                  {layer.name}
                </h2>
                <p className="text-text-secondary mt-4 text-lg leading-relaxed text-pretty">
                  {layer.intro}
                </p>
              </div>
            </div>

            <div className="mt-12 flex flex-col gap-10">
              {layer.lanes.map((lane) => (
                <div key={lane.caption}>
                  <p className="eyebrow mb-3 flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={`h-px w-6 ${lane.edge === "sync" ? "bg-accent" : "border-signal border-t border-dashed"}`}
                    />
                    {lane.caption}
                  </p>
                  <FlowChain
                    steps={lane.steps}
                    edge={lane.edge}
                    label={lane.caption}
                  />
                </div>
              ))}
            </div>

            <dl className="mt-14 grid gap-x-12 gap-y-8 md:grid-cols-2">
              {layer.reasons.map((reason) => (
                <div key={reason.term} className="border-border border-t pt-5">
                  <dt className="text-text-primary text-base font-semibold">
                    {reason.term}
                  </dt>
                  <dd className="text-text-secondary mt-2 text-base leading-relaxed">
                    {reason.body}
                  </dd>
                </div>
              ))}
            </dl>

            <p className="text-text-tertiary mt-10 font-mono text-xs break-words">
              Read from: {layer.sources}
            </p>
          </div>
        </section>
      ))}

      <section className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-8">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-20">
          <h2 className="text-text-primary text-2xl font-semibold tracking-tight">
            How these claims were checked
          </h2>
          <div className="text-text-secondary max-w-2xl space-y-4 text-base leading-relaxed">
            <p>
              Each statement on this page was read from the backend source files
              named under its layer. None was checked by running the system, so
              the page describes what the code does, not what any deployment is
              currently doing.
            </p>
            <p>
              To see the running system, open{" "}
              <Link
                href="/operations"
                className="text-accent underline underline-offset-4"
              >
                Live Operations
              </Link>{" "}
              for stream state or{" "}
              <Link
                href="/investigations"
                className="text-accent underline underline-offset-4"
              >
                Investigations
              </Link>{" "}
              for individual executions.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
