import type { Metadata } from "next";
import Link from "next/link";
import { BrowserFrame } from "@/components/browser-frame";
import { Topology } from "@/components/topology";

export const metadata: Metadata = {
  title: "Fin-Sentry",
};

interface Decision {
  title: string;
  body: string;
  tradeoff: string;
  source: string;
}

// Every statement was read from the backend source, not run. The source
// line names where. Where the code is narrower than the aspiration, the
// tradeoff line says so.
const DECISIONS: Decision[] = [
  {
    title: "Bound the request path",
    body: "The model call gets a 20 second wall-time budget, a 15 second cap per attempt, and a circuit breaker that opens after five failures and recovers after 30 seconds. A dead model returns an immediate 503 instead of holding the gateway open.",
    tradeoff:
      "The budget covers the downstream call, not the whole request. The one evaluation step on this path, the faithfulness check, fails open when Gemini is unavailable.",
    source: "finsentry/gateway/main.py, finsentry/gateway/circuit_breaker.py",
  },
  {
    title: "Separate traffic from evaluation",
    body: "The gateway publishes one event to Redpanda and moves on. Judges read the topic on their own schedule and write verdicts back. RisingWave reads those topics and keeps the views the dashboard queries.",
    tradeoff:
      "Delivery is at-most-once, so an event can be lost. The platform treats evaluation data as telemetry, not a ledger, and says so.",
    source: "finsentry/events/producer.py, docs/adr/006",
  },
  {
    title: "Make frontier review deterministic",
    body: "The sampler hashes the trace id with SHA-256 and keeps the trace when the result modulo ten is zero. A retry or a replay lands on the same side of the line, so which traces get a second review never depends on load.",
    tradeoff:
      "The rate is a fixed one in ten. Adaptive sampling was designed and deferred.",
    source: "finsentry/frontier/sampling.py",
  },
  {
    title: "Do not trust a judge by default",
    body: "The frontier judge is scored against a labeled financial hallucination benchmark with Cohen’s kappa. The drift thresholds are asymmetric, 0.43 to enter drift and 0.54 to recover, so the state does not flap around a single value.",
    tradeoff:
      "The only reading on record is one manual run. The controller that applies the thresholds is built and tested but not yet wired into the gateway or the consumers, and the flash judge is not calibrated.",
    source: "finsentry/reliability/health.py, finsentry/mcp/tools/drift.py",
  },
  {
    title: "Preserve every execution",
    body: "Overview and Live Operations summarize. Investigations does not. Each persisted execution is one row, including blocks and errors, with a filter for the cases that matter most, such as the flash and frontier judges disagreeing.",
    tradeoff:
      "Summary views group repeated questions. That rule applies only there, and every grouped row links back to its individual executions.",
    source: "finsentry/events/trace_api.py",
  },
  {
    title: "Diagnose from structured reasons",
    body: "A blocked request persists a reason code, the name of the rail that fired, and the ids of the chunks that were retrieved. The answer field stays empty. An engineer can tell what stopped a request without reading model output.",
    tradeoff:
      "This describes the persisted record. It is not a claim about every response the gateway returns.",
    source: "finsentry/gateway/main.py, finsentry/events/schema.py",
  },
  {
    title: "Generate locally, evaluate on hosted models",
    body: "Generation runs on a local Ollama model, so the answers under test do not depend on a paid API. Both judge tiers run on hosted Gemini, inside the project’s free-tier credit.",
    tradeoff:
      "The frontier judge is not local. The local models in the original plan did not ship: HHEM is implemented but disabled, and Lynx and Prometheus have no adapter.",
    source: "finsentry/judges/flash_judge.py, finsentry/frontier/adapters/",
  },
];

const LIMITS: { title: string; body: string }[] = [
  {
    title: "Calibration is a last known reading",
    body: "It comes from one manual canary run saved to disk. It is not a scheduled or live monitor, and it covers the frontier judge only.",
  },
  {
    title: "Red Team is not built",
    body: "There is no stored scenario registry and the MCP tool for running scenarios is not registered. The route says so instead of showing a mock.",
  },
  {
    title: "Frontier sampling is fixed",
    body: "One trace in ten, with no backpressure control. The ensemble resolves to a single hosted judge today.",
  },
  {
    title: "Live charts only show what arrived",
    body: "The activity chart on Live Operations fills from the stream while the page is open. There is no stored history behind it.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      <section className="relative isolate overflow-hidden">
        <div
          aria-hidden="true"
          className="field-glow pointer-events-none absolute inset-0 -z-10"
        />
        <div
          aria-hidden="true"
          className="field-grid pointer-events-none absolute inset-0 -z-10"
        />
        <div className="mx-auto w-full max-w-7xl px-4 pt-16 pb-12 sm:px-8 sm:pt-24">
          <p className="eyebrow rise">
            AI reliability and evaluation for financial RAG
          </p>
          <h1 className="text-text-primary rise rise-2 mt-5 max-w-4xl text-5xl leading-[1.04] font-semibold tracking-tight text-balance sm:text-7xl">
            Guard every answer. Judge it.{" "}
            <span className="display-accent text-accent">
              Keep the evidence.
            </span>
          </h1>
          <div className="rise rise-3 mt-8 grid max-w-5xl gap-x-12 gap-y-5 lg:grid-cols-2">
            <p className="text-text-primary text-lg leading-relaxed text-pretty">
              Fin-Sentry sits in front of a RAG endpoint that answers questions
              about SEC filings. Input rails stop unsafe requests, a bounded
              model call writes the answer, and output rails check it before it
              is returned.
            </p>
            <p className="text-text-secondary text-lg leading-relaxed text-pretty">
              Evaluation runs off the request path. A flash judge scores every
              delivered answer. A deterministic one-in-ten sample gets a second,
              rubric-based review. Calibration measures that judge against a
              labeled benchmark, and every execution stays inspectable.
            </p>
          </div>
          <div className="rise rise-3 mt-10 flex flex-wrap gap-3">
            <Link
              href="/overview"
              className="bg-text-primary text-background hover:bg-text-primary/90 inline-flex min-h-12 items-center rounded-lg px-6 text-base font-medium transition-colors"
            >
              Open the command center
            </Link>
            <Link
              href="/architecture"
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-12 items-center rounded-lg border px-6 text-base font-medium transition-colors"
            >
              Read the architecture
            </Link>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="topology-heading"
        className="mx-auto w-full max-w-7xl px-4 pb-24 sm:px-8"
      >
        <div className="mb-8 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="eyebrow">System topology</p>
            <h2
              id="topology-heading"
              className="text-text-primary mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              One request path.{" "}
              <span className="display-accent text-signal">
                A separate evaluation plane.
              </span>
            </h2>
          </div>
          <p className="text-text-secondary max-w-md text-base leading-relaxed">
            The request is answered before evaluation starts. Hover or focus a
            stage to see what it does and why it exists.
          </p>
        </div>
        <Topology />
      </section>

      <section
        aria-labelledby="decisions-heading"
        className="border-border border-t"
      >
        <div className="mx-auto grid w-full max-w-7xl gap-12 px-4 py-24 sm:px-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-20">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <p className="eyebrow">Engineering decisions</p>
            <h2
              id="decisions-heading"
              className="text-text-primary mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              Seven choices, each with its{" "}
              <span className="display-accent text-accent">cost</span>.
            </h2>
            <p className="text-text-secondary mt-5 text-base leading-relaxed">
              Each decision names what it buys and what it gives up. The source
              line says where in the code it can be checked.
            </p>
          </div>
          <ol className="border-border divide-border divide-y border-t">
            {DECISIONS.map((decision, i) => (
              <li
                key={decision.title}
                className="grid gap-x-8 gap-y-3 py-9 first:pt-9 sm:grid-cols-[3.5rem_1fr]"
              >
                <span
                  aria-hidden="true"
                  className="text-text-tertiary font-mono text-sm tabular-nums"
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className="text-text-primary text-xl font-semibold tracking-tight">
                    {decision.title}
                  </h3>
                  <p className="text-text-secondary mt-3 text-base leading-relaxed">
                    {decision.body}
                  </p>
                  <p className="text-text-primary mt-3 text-base leading-relaxed">
                    <span className="text-warning font-medium">Cost. </span>
                    {decision.tradeoff}
                  </p>
                  <p className="text-text-tertiary mt-3 font-mono text-xs break-words">
                    {decision.source}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section
        aria-labelledby="evidence-heading"
        className="border-border bg-background-elevated border-t"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:px-8">
          <div className="max-w-2xl">
            <p className="eyebrow">Product evidence</p>
            <h2
              id="evidence-heading"
              className="text-text-primary mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              The running application, captured against the live stack.
            </h2>
            <p className="text-text-secondary mt-4 text-base leading-relaxed">
              Every score, count and badge is a persisted field from the demo
              corpus. Nothing is staged or edited.
            </p>
          </div>

          <figure className="mt-14">
            <BrowserFrame
              src="/screenshots/trace-detail.png"
              route="/investigations"
              alt="The trace detail drawer for a real disagreement: the flash judge scored an Amazon net income answer 1.000 and the frontier judge scored it 0.000, with the frontier judge’s written reasoning."
            />
            <figcaption className="text-text-secondary mt-4 max-w-2xl text-base leading-relaxed">
              <span className="text-text-primary font-medium">
                The disagreement that justifies the second tier.
              </span>{" "}
              The flash judge scored this Amazon answer as fully faithful. The
              frontier judge scored it zero and explained that the retrieved
              context did contain the figure.
            </figcaption>
          </figure>

          <div className="mt-16 grid gap-10 lg:grid-cols-2">
            <figure>
              <BrowserFrame
                src="/screenshots/overview.png"
                route="/overview"
                alt="The Overview command center, showing system state, the attention required list, evaluation coverage and the reliability pipeline."
              />
              <figcaption className="text-text-secondary mt-4 text-base leading-relaxed">
                <span className="text-text-primary font-medium">Overview.</span>{" "}
                What needs attention, why it matters, and where to look.
              </figcaption>
            </figure>
            <figure>
              <BrowserFrame
                src="/screenshots/operations.png"
                route="/operations"
                alt="Live Operations, showing connection and freshness state, throughput and latency readouts, the calibration instrument and an operational timeline."
              />
              <figcaption className="text-text-secondary mt-4 text-base leading-relaxed">
                <span className="text-text-primary font-medium">
                  Live Operations.
                </span>{" "}
                Stream freshness, latency, judge usage and the calibration
                reading, each labeled with its scope.
              </figcaption>
            </figure>
          </div>

          <figure className="mt-16">
            <BrowserFrame
              src="/screenshots/investigations.png"
              route="/investigations"
              alt="The Investigations workspace: a table with one row per persisted execution, with human-readable outcomes, judge state and frontier sampling."
            />
            <figcaption className="text-text-secondary mt-4 max-w-2xl text-base leading-relaxed">
              <span className="text-text-primary font-medium">
                Investigations.
              </span>{" "}
              One row per execution, never grouped or deduplicated.
            </figcaption>
          </figure>
        </div>
      </section>

      <section
        aria-labelledby="limits-heading"
        className="border-border border-t"
      >
        <div className="mx-auto grid w-full max-w-7xl gap-12 px-4 py-24 sm:px-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-20">
          <div>
            <p className="eyebrow">Known limits</p>
            <h2
              id="limits-heading"
              className="text-text-primary mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              What this build does not do yet.
            </h2>
          </div>
          <dl className="grid gap-x-12 gap-y-8 sm:grid-cols-2">
            {LIMITS.map((limit) => (
              <div key={limit.title} className="border-border border-t pt-5">
                <dt className="text-text-primary text-base font-semibold">
                  {limit.title}
                </dt>
                <dd className="text-text-secondary mt-2 text-base leading-relaxed">
                  {limit.body}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <footer className="border-border border-t">
        <div className="text-text-tertiary mx-auto flex w-full max-w-7xl flex-col gap-2 px-4 py-8 text-sm sm:flex-row sm:justify-between sm:px-8">
          <p>
            Fin-Sentry is a portfolio project. All data shown comes from a local
            demo corpus of ten SEC filers.
          </p>
          <p>Built with Next.js, FastAPI, Redpanda and RisingWave.</p>
        </div>
      </footer>
    </div>
  );
}
