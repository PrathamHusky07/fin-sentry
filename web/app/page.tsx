import type { Metadata } from "next";
import Link from "next/link";
import { BrowserFrame } from "@/components/browser-frame";
import { DecisionLedger } from "@/components/decision-ledger";
import { HeroFlow } from "@/components/hero-flow";
import { Topology } from "@/components/topology";

export const metadata: Metadata = {
  title: "Fin-Sentry",
};

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      <section className="mx-auto w-full max-w-7xl px-4 pt-10 pb-14 sm:px-8 sm:pt-12">
        <h1 className="text-text-primary rise max-w-4xl text-4xl leading-[1.06] font-semibold tracking-tight sm:text-6xl">
          <span className="block">Guard every answer. Judge it.</span>
          <span className="block">Keep the evidence.</span>
        </h1>
        <div className="rise rise-2 mt-6 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <p className="text-text-secondary max-w-2xl text-lg leading-relaxed text-pretty">
            Fin-Sentry sits in front of a RAG endpoint that answers questions
            about SEC filings. Rails guard the request, judges score each answer
            after it is sent, and every execution stays inspectable.
          </p>
          <div className="flex flex-wrap gap-3">
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
        <div className="rise rise-3 mt-8">
          <HeroFlow />
        </div>
      </section>

      <section
        aria-labelledby="topology-heading"
        className="border-border border-t"
      >
        <div className="mx-auto w-full max-w-7xl px-4 py-24 sm:px-8">
          <div className="mb-10 max-w-2xl">
            <h2
              id="topology-heading"
              className="text-text-primary text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
            >
              One question, followed through the system
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
        className="border-border border-t"
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
              Every row is a choice made in this build. Each states the problem
              it answered, what it gave up and what it made true.
            </p>
          </div>
          <DecisionLedger />
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

      <footer className="border-border border-t">
        <div className="text-text-tertiary mx-auto flex w-full max-w-7xl flex-col gap-2 px-4 py-8 text-sm sm:flex-row sm:justify-between sm:px-8">
          <p>
            Fin-Sentry is a portfolio project. All data shown comes from a
            demonstration corpus of ten SEC filers.
          </p>
          <p>Built with Next.js, FastAPI, Redpanda and RisingWave.</p>
        </div>
      </footer>
    </div>
  );
}
