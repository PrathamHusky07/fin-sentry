import type { Metadata } from "next";
import Link from "next/link";
import { AgentGuide } from "@/components/agent/agent-guide";
import { AgentLifecycle } from "@/components/agent/agent-lifecycle";
import { IncidentList } from "@/components/incidents/incident-list";
import { SectionRail } from "@/components/incidents/section-rail";
import { StartIncident } from "@/components/incidents/start-incident";

export const metadata: Metadata = {
  title: "Agent | Fin-Sentry",
};

const SECTIONS = [
  { id: "lifecycle", label: "Lifecycle" },
  { id: "investigations", label: "Investigations" },
  { id: "guide", label: "How to read one" },
];

/**
 * The Incident Response Agent: what it investigates, how one investigation runs, and every
 * stored session it has produced. Nothing on this route starts an investigation or calls a
 * model. Only the start form inside the investigations section can, and only on submit.
 */
export default function AgentPage() {
  return (
    <div className="ctx ctx-forensic mobile-readable flex-1">
      <SectionRail sections={SECTIONS} />
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-8">
        <header className="flex flex-col gap-6 pt-12 pb-10 sm:pt-16 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="eyebrow">
              What did the agent examine, and what could it prove?
            </p>
            <h1 className="text-text-primary mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Incident Response Agent
            </h1>
            <p className="text-text-secondary mt-4 text-lg leading-relaxed text-pretty">
              When something goes wrong, the agent examines the platform’s
              stored evidence. A model proposes competing explanations. Code
              runs read-only queries, checks each explanation against the
              records, and reports only what it can cite. When the records do
              not support a cause, it abstains.
            </p>
            <p className="text-text-secondary mt-3 text-base leading-relaxed text-pretty">
              A wrong root cause is worse than no answer, so the agent is built
              to be checked and not trusted. Every investigation below is a
              stored session. Opening one runs nothing.
            </p>
          </div>
          <Link
            href="/architecture#incident-response-agent"
            className="text-accent hover:text-text-primary inline-flex min-h-11 shrink-0 items-center text-base underline underline-offset-4 sm:text-sm"
          >
            How the agent is built
          </Link>
        </header>

        <section
          id="lifecycle"
          aria-labelledby="lifecycle-heading"
          className="border-border border-t py-12"
        >
          <h2
            id="lifecycle-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            One investigation, step by step
          </h2>
          <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed">
            Only the plan comes from a model. Select a step to see what it does
            and where the investigation can stop.
          </p>
          <div className="mt-6">
            <AgentLifecycle />
          </div>
        </section>

        <section
          id="investigations"
          aria-labelledby="investigations-heading"
          className="border-border border-t py-12"
        >
          <h2
            id="investigations-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            Stored investigations
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-3xl text-base leading-relaxed">
            Each row is one session of the agent on one incident. Open one to
            see the competing hypotheses, the records behind each, the queries
            that ran and what was not established.
          </p>
          <div className="mb-8">
            <StartIncident />
          </div>
          <IncidentList />
        </section>

        <section
          id="guide"
          aria-labelledby="guide-heading"
          className="border-border border-t py-12 pb-20"
        >
          <AgentGuide />
        </section>
      </div>
    </div>
  );
}
