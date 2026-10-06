import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ArchitectureVisual } from "@/components/architecture-visual";

export const metadata: Metadata = {
  title: "Fin-Sentry",
};

const SCREENSHOTS = [
  {
    src: "/screenshots/overview.png",
    alt: "The Overview command center, showing calibration state, evaluation completion, live metric tiles, attention-required signals, and the judge-state distribution.",
    caption:
      "Overview: the command center. Calibration state, judge-state distribution, and blocked requests, all read from persisted data, not estimated.",
  },
  {
    src: "/screenshots/investigations.png",
    alt: "The Investigations workspace, showing a searchable, filterable table of real persisted requests with status and judge-state columns.",
    caption:
      "Investigations: every real request, searchable and filterable. Rows are never grouped or deduplicated here.",
  },
  {
    src: "/screenshots/trace-detail.png",
    alt: "A trace detail view showing a real disagreement: the flash judge scored an answer 1.000 and the frontier judge scored it 0.000, with the frontier judge's written reasoning.",
    caption:
      "A real disagreement the platform caught. The flash judge scored this Amazon answer fully faithful. The frontier judge scored it zero and explained why.",
  },
] as const;

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      <section className="mx-auto w-full max-w-5xl px-4 pt-16 pb-12 sm:px-6 sm:pt-24">
        <h1 className="text-text-primary text-4xl font-semibold tracking-tight sm:text-5xl">
          Fin-Sentry
        </h1>
        <p className="text-text-secondary mt-4 max-w-2xl text-lg leading-relaxed">
          An AI reliability and evaluation platform for financial RAG. It
          catches unsafe, unsupported, and mis-evaluated answers before they
          reach a user.
        </p>

        <div className="mt-10">
          <p className="text-text-secondary text-xs tracking-wide uppercase">
            The real execution path
          </p>
          <p className="text-text-secondary mt-1.5 max-w-2xl text-sm leading-relaxed">
            Every request moves through this path. Guardrails check input,
            retrieval, and output. A flash judge scores every response. A
            sampled frontier judge checks harder cases. Both are checked against
            human-labeled data on a weekly calibration cycle.
          </p>
          <div className="mt-6">
            <ArchitectureVisual />
          </div>
        </div>

        <div className="mt-10">
          <Link
            href="/overview"
            className="focus-visible:outline-accent border-border bg-background-elevated text-text-primary hover:bg-surface inline-flex min-h-11 items-center rounded-md border px-4 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Open the operations console
          </Link>
        </div>
      </section>

      <section className="border-border bg-background-elevated border-t">
        <div className="mx-auto w-full max-w-5xl px-4 py-16 sm:px-6">
          <h2 className="text-text-primary text-2xl font-semibold tracking-tight">
            What the platform actually looks like
          </h2>
          <p className="text-text-secondary mt-2 max-w-2xl text-sm leading-relaxed">
            Real screens from the running application, captured against the live
            stack. Every number, badge, and score shown is a persisted field,
            not a mockup.
          </p>

          <div className="mt-10 flex flex-col gap-14">
            {SCREENSHOTS.map((shot) => (
              <figure key={shot.src}>
                <div className="border-border overflow-hidden rounded-lg border">
                  <Image
                    src={shot.src}
                    alt={shot.alt}
                    width={1440}
                    height={900}
                    className="w-full"
                  />
                </div>
                <figcaption className="text-text-secondary mt-3 max-w-2xl text-sm leading-relaxed">
                  {shot.caption}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-5xl px-4 py-16 sm:px-6">
        <h2 className="text-text-primary text-2xl font-semibold tracking-tight">
          Engineering choices
        </h2>
        <dl className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <dt className="text-text-primary text-sm font-medium">
              Zero paid APIs in the critical path
            </dt>
            <dd className="text-text-secondary mt-1 text-sm leading-relaxed">
              The flash judge runs on the Google Cloud free-tier credit. Every
              other model, including the frontier judge, runs locally.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-sm font-medium">
              Defense in depth, not a single filter
            </dt>
            <dd className="text-text-secondary mt-1 text-sm leading-relaxed">
              Separate guardrails check the request, the retrieved context, and
              the generated answer. A block at any stage is traced back to the
              specific rail that caught it.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-sm font-medium">
              Judges are calibrated, not assumed accurate
            </dt>
            <dd className="text-text-secondary mt-1 text-sm leading-relaxed">
              Both judge tiers are checked against a human-labeled financial
              golden set using Cohen&apos;s kappa, with explicit drift
              thresholds.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-sm font-medium">
              Every trace is inspectable
            </dt>
            <dd className="text-text-secondary mt-1 text-sm leading-relaxed">
              Nothing is sampled away from view. A blocked request, a judge
              disagreement, or a judge-pipeline error all land in Investigations
              as a real, searchable row.
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
