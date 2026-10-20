import type { Metadata } from "next";
import Link from "next/link";
import { EvaluationTopology } from "@/components/arch/evaluation-topology";
import { EventLanes } from "@/components/arch/event-lanes";
import { IncidentInvestigatorLoop } from "@/components/arch/investigator-loop";
import { InterfaceHub } from "@/components/arch/interface-hub";
import { RequestPipeline } from "@/components/arch/request-pipeline";
import { LayerCards, LayerRail } from "@/components/arch/layer-nav";
import { ReasonList } from "@/components/arch/reason-list";
import { LAYERS, type Layer } from "@/lib/architecture-layers";

export const metadata: Metadata = {
  title: "Architecture | Fin-Sentry",
};

const DIAGRAM: Record<Layer["id"], React.ReactNode> = {
  "request-path": <RequestPipeline />,
  "evaluation-plane": <EvaluationTopology />,
  "event-infrastructure": <EventLanes />,
  "operational-interface": <InterfaceHub />,
  "incident-investigator": <IncidentInvestigatorLoop />,
};

export default function ArchitecturePage() {
  return (
    <div className="ctx ctx-blueprint flex flex-1 flex-col">
      <header className="border-border border-b">
        <div className="mx-auto w-full max-w-7xl px-4 pt-14 pb-12 sm:px-8 sm:pt-16">
          <p className="text-text-tertiary text-sm">Architecture</p>
          <h1 className="text-text-primary mt-3 max-w-4xl text-4xl leading-[1.06] font-semibold tracking-tight text-balance sm:text-6xl">
            How Fin-Sentry is built, and why
          </h1>
          <p className="text-text-secondary mt-6 max-w-2xl text-lg leading-relaxed text-pretty">
            Five layers, from the request that arrives to the investigator that
            examines an incident afterward. The read tools exist today, and the
            tool that would run Red Team scenarios is not registered yet. Each
            layer is drawn the way its data actually moves.
          </p>

          <LayerCards />
        </div>
      </header>

      <LayerRail />

      {LAYERS.map((layer) => (
        <section
          key={layer.id}
          id={layer.id}
          aria-labelledby={`${layer.id}-heading`}
          className="border-border scroll-mt-[calc(var(--nav-h)+3rem)] border-b"
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

            <div className="ctx ctx-quiet border-line bg-background-elevated/40 mt-14 overflow-hidden rounded-2xl border p-6 sm:p-8">
              <p className="eyebrow mb-2">Why it is built this way</p>
              <ReasonList reasons={layer.reasons} layerId={layer.id} />
            </div>
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
