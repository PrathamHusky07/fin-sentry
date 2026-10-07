import type { Metadata } from "next";
import Link from "next/link";
import { EvaluationTopology } from "@/components/arch/evaluation-topology";
import { EventLanes } from "@/components/arch/event-lanes";
import { InterfaceHub } from "@/components/arch/interface-hub";
import { RequestPipeline } from "@/components/arch/request-pipeline";
import { ArchLegend } from "@/components/arch/svg-parts";
import { LAYERS, type Layer } from "@/lib/architecture-layers";

export const metadata: Metadata = {
  title: "Architecture — Fin-Sentry",
};

const DIAGRAM: Record<Layer["id"], React.ReactNode> = {
  "request-path": (
    <>
      <RequestPipeline />
      <div className="hidden lg:block">
        <ArchLegend items={["sync", "async"]} />
      </div>
    </>
  ),
  "evaluation-plane": <EvaluationTopology />,
  "event-infrastructure": <EventLanes />,
  "operational-interface": <InterfaceHub />,
};

export default function ArchitecturePage() {
  return (
    <div className="flex flex-col">
      <header className="border-border border-b">
        <div className="mx-auto w-full max-w-7xl px-4 pt-14 pb-12 sm:px-8 sm:pt-16">
          <p className="text-text-tertiary text-sm">Architecture</p>
          <h1 className="text-text-primary mt-3 max-w-4xl text-4xl leading-[1.06] font-semibold tracking-tight text-balance sm:text-6xl">
            How Fin-Sentry is built, and why
          </h1>
          <p className="text-text-secondary mt-6 max-w-2xl text-lg leading-relaxed text-pretty">
            Four layers, from the request that arrives to the tools an engineer
            uses afterward. Each one is drawn the way its data actually moves.
          </p>

          <nav aria-label="Architecture layers" className="mt-10">
            <ul className="border-border-strong grid border-t sm:grid-cols-2 lg:grid-cols-4">
              {LAYERS.map((layer) => (
                <li
                  key={layer.id}
                  className="border-border border-b lg:border-r lg:border-b-0 lg:last:border-r-0"
                >
                  <a
                    href={`#${layer.id}`}
                    className="hover:bg-surface/60 flex min-h-11 flex-col gap-1.5 px-1 py-5 transition-colors lg:px-5 lg:first:pl-0"
                  >
                    <span className="text-text-primary text-lg font-semibold tracking-tight">
                      {layer.name}
                    </span>
                    <span className="text-text-secondary text-sm leading-snug">
                      {layer.question}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
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

            <div className="mt-12">{DIAGRAM[layer.id]}</div>

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
              Each statement on this page was read from the backend source, not
              checked by running the system. The page describes what the code
              does, not what any deployment is currently doing.
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
