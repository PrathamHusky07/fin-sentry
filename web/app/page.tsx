import type { Metadata } from "next";
import type { CSSProperties } from "react";
import Link from "next/link";
import { BrowserFrame } from "@/components/browser-frame";
import { DecisionNavigator } from "@/components/decision-navigator";
import { HeroConstellation } from "@/components/hero-constellation";
import { StageCards } from "@/components/stage-cards";
import { Topology } from "@/components/topology";
import demoRecord from "@/lib/demo-record.json";

export const metadata: Metadata = {
  title: "Fin-Sentry",
};

// Pixel size of each capture in public/screenshots, so the frame reserves
// the right space and scrolls the real, full-length screen.
const SHOT = {
  traceDetail: { width: 1440, height: 2000 },
  overview: { width: 1440, height: 3200 },
  operations: { width: 1440, height: 2407 },
  investigations: { width: 1440, height: 2200 },
} as const;

// Position of an element in the hero entrance; globals.css turns it into a delay.
function step(i: number): CSSProperties {
  return { "--i": i } as CSSProperties;
}

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      <section className="ctx ctx-hero">
        <div aria-hidden="true" className="hero-field">
          <div className="hero-depth">
            <span className="hero-field-a" />
            <span className="hero-field-b" />
            <span className="hero-field-c" />
            <span className="hero-aurora" />
          </div>
          <span className="hero-scan">
            <span className="hero-scan-dots">
              <span className="hero-scan-band" />
            </span>
          </span>
        </div>
        <div className="mx-auto w-full max-w-7xl px-4 pt-10 pb-16 sm:px-8 sm:pt-12 sm:pb-20">
          <h1 className="text-text-primary max-w-6xl text-4xl leading-[1.06] font-semibold tracking-tight sm:text-6xl">
            <span className="hero-in block" style={step(0)}>
              Score the answer.
            </span>
            <span className="hero-in block" style={step(1)}>
              Audit the judge.
            </span>
            <span className="hero-in block" style={step(2)}>
              Explain the failure from the record.
            </span>
          </h1>
          <div className="mt-6 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <p
              className="text-text-secondary hero-in max-w-2xl text-lg leading-relaxed text-pretty"
              style={step(3)}
            >
              Fin-Sentry is an AI reliability and evaluation platform that
              guards the question, the retrieved text and the answer. Delivered
              answers are scored by a first judge, and a second-opinion judge,
              calibrated independently against labeled data, reviews a sample of
              them. When an answer fails, an incident agent reconstructs what
              happened from read-only records and abstains when they cannot
              support an explanation. The reference workload is financial RAG
              over SEC filings, and the recorded Red Team and agent runs can be
              inspected.
            </p>
            <div className="hero-in flex flex-wrap gap-3" style={step(4)}>
              <Link
                href="/overview"
                className="bg-text-primary text-background hover:bg-text-primary/90 inline-flex min-h-12 items-center rounded-lg px-6 text-base font-medium shadow-[0_10px_30px_-12px_var(--glow-accent)] transition-[background-color,box-shadow] duration-[var(--dur-base)] hover:shadow-[0_14px_36px_-12px_var(--glow-accent)]"
              >
                Open the command center
              </Link>
              <Link
                href="/architecture"
                className="border-line-active text-text-primary hover:bg-surface-hover hover:border-line-active inline-flex min-h-12 items-center rounded-lg border px-6 text-base font-medium transition-colors"
              >
                Read the architecture
              </Link>
            </div>
          </div>
          <div className="rise rise-3 mt-6 sm:mt-8">
            <HeroConstellation />
          </div>
          <div className="mt-8">
            <h2 className="sr-only">An answer’s life in five stages</h2>
            <StageCards />
          </div>
        </div>
      </section>

      <section
        aria-labelledby="topology-heading"
        className="ctx ctx-topology border-border border-t"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:px-8">
          <div className="mb-10 max-w-2xl">
            <h2
              id="topology-heading"
              className="text-text-primary text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              Follow one question through Fin-Sentry
            </h2>
            <p className="text-text-secondary mt-4 text-base leading-relaxed">
              The user has an answer before evaluation starts. Everything that
              checks that answer afterward runs on its own plane and leaves its
              verdicts in the evidence store.
            </p>
          </div>
          <Topology />
        </div>
      </section>

      <section
        aria-labelledby="decisions-heading"
        className="ctx ctx-quiet border-border border-t"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:px-8">
          <div className="mb-10 max-w-2xl">
            <h2
              id="decisions-heading"
              className="text-text-primary text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              Six decisions, each with its cost
            </h2>
            <p className="text-text-secondary mt-4 text-base leading-relaxed">
              Every one is a choice made in this build. Select a decision to
              read the problem it answered, what it gave up and what it made
              true.
            </p>
          </div>
          <DecisionNavigator />
        </div>
      </section>

      <section
        aria-labelledby="evidence-heading"
        className="ctx ctx-quiet border-border bg-background-elevated border-t"
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
              corpus. Nothing is staged or edited. Scroll inside a window to
              read more of the real screen.
            </p>
          </div>

          <figure className="mt-14">
            <BrowserFrame
              src="/screenshots/trace-detail.png"
              route="/investigations"
              href={`/investigations?trace=${demoRecord.reask.app_trace_id}`}
              cta="Open the Amazon trace"
              {...SHOT.traceDetail}
              alt="The trace detail drawer for a real disagreement: the flash judge scored an Amazon net income answer 1.000 and the frontier judge scored it 0.000, with the frontier judge’s written reasoning."
            />
            <figcaption className="text-text-secondary mt-4 max-w-2xl text-base leading-relaxed">
              <span className="text-text-primary font-medium">
                The disagreement that justifies the second tier.
              </span>{" "}
              The flash judge scored this Amazon answer fully faithful. The
              frontier judge read the same retrieved context, found the net
              income figure in it and scored the answer zero. A gap like this is
              what a second opinion exists to surface.{" "}
              <span className="text-text-tertiary">
                This capture is a historical example. The link opens the same
                Amazon question asked again, which the pipeline recorded as a
                separate trace without a frontier score.
              </span>
            </figcaption>
          </figure>

          <div className="mt-16 grid gap-10 lg:grid-cols-2">
            <figure>
              <BrowserFrame
                src="/screenshots/overview.png"
                route="/overview"
                href="/overview"
                cta="Open command center"
                {...SHOT.overview}
                alt="The Overview command center: the system state with the frontier judge’s agreement drawn against its thresholds, and the Amazon disagreement featured with its returned answer and both scores."
              />
              <figcaption className="text-text-secondary mt-4 text-base leading-relaxed">
                <span className="text-text-primary font-medium">Overview.</span>{" "}
                What needs attention, why it matters, and where to look.
              </figcaption>
            </figure>
            <figure>
              <BrowserFrame
                src="/screenshots/operations-day12-s8.png"
                route="/operations"
                href="/operations"
                cta="Open Live Operations"
                {...SHOT.operations}
                alt="Live Operations as captured: four statements of what the platform covers, the evaluation telemetry cards for the flash judge and the frontier tier, the calibration reading with its thresholds, and the gateway health-route round trip of 0.26 ms median."
              />
              <figcaption className="text-text-secondary mt-4 text-base leading-relaxed">
                <span className="text-text-primary font-medium">
                  Live Operations.
                </span>{" "}
                Evaluation telemetry from the judges, the frontier judge&rsquo;s
                calibration reading and a gateway health-route timing, each
                labeled with its window. This is a captured state, not a live
                connection.
              </figcaption>
            </figure>
          </div>

          <figure className="mt-16">
            <BrowserFrame
              src="/screenshots/investigations.png"
              route="/investigations"
              href="/investigations"
              cta="Open forensic workspace"
              {...SHOT.investigations}
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
    </div>
  );
}
