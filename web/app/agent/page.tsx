import type { Metadata } from "next";
import Link from "next/link";
import { AgentGuide } from "@/components/agent/agent-guide";
import { CaseExplorer } from "@/components/agent/case-explorer";
import { InvestigationMap } from "@/components/agent/investigation-map";
import { RecordStates } from "@/components/agent/record-states";
import { SectionRail } from "@/components/incidents/section-rail";
import { StartIncident } from "@/components/incidents/start-incident";
import { AMAZON_TRACE_ID, lookupTrace, storedCounts } from "@/lib/agent-data";

export const metadata: Metadata = {
  title: "Agent | Fin-Sentry",
};

const SECTIONS = [
  { id: "lifecycle", label: "How it works" },
  { id: "investigations", label: "Cases" },
  { id: "records", label: "Record states" },
  { id: "guide", label: "Reading a case" },
];

/**
 * The Incident Response Agent: how one investigation runs, then every stored case. Nothing on
 * this route starts an investigation or calls a model. Only the start form, closed until it is
 * opened, can, and only on submit. The two reads this page makes on the server are a
 * listing of stored cases and a lookup of one trace, both read only.
 */
export default async function AgentPage() {
  const [counts, lookup] = await Promise.all([
    storedCounts(),
    lookupTrace(AMAZON_TRACE_ID),
  ]);
  return (
    <div className="ctx ctx-forensic mobile-readable flex-1">
      <SectionRail sections={SECTIONS} />
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-8">
        <header className="flex flex-col gap-6 pt-12 pb-8 sm:pt-16 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="eyebrow">
              What did the investigator examine, and what do the records
              support?
            </p>
            <h1 className="text-text-primary mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Incident Response Agent
            </h1>
            <p className="text-text-secondary mt-4 text-lg leading-relaxed text-pretty">
              The investigator weighs competing explanations against the
              recorded evidence. Evidence is retrieved through approved,
              read-only tools, and every claim cites the records behind it. A
              conclusion requires supporting evidence. When the evidence is
              insufficient, the investigator abstains.
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
          className="border-border border-t py-10"
        >
          <h2
            id="lifecycle-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            How an investigation runs
          </h2>
          <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed">
            Six stages around one incident. Only planning calls a model. Select
            a stage to see what it does and where an investigation can stop.
          </p>
          <div className="mt-4">
            <InvestigationMap />
          </div>
        </section>

        <section
          id="investigations"
          aria-labelledby="investigations-heading"
          className="border-border border-t py-10"
        >
          <h2
            id="investigations-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            Cases
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-3xl text-base leading-relaxed">
            Each case is one stored investigation of one incident. Select a case
            to read its summary, then open the case file for the hypotheses, the
            evidence and the decision trail. Selecting a case runs nothing.
          </p>
          <CaseExplorer />
          <div className="mt-8">
            <StartIncident />
          </div>
        </section>

        <section
          id="records"
          aria-labelledby="records-heading"
          className="border-border border-t py-10"
        >
          <h2
            id="records-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            Where a record comes from
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-3xl text-base leading-relaxed">
            Every case and every cited record is one of four kinds. The page
            names the kind and never shows one in place of another.
          </p>
          <RecordStates counts={counts} lookup={lookup} />
        </section>

        <section
          id="guide"
          aria-labelledby="guide-heading"
          className="border-border border-t py-10 pb-20"
        >
          <AgentGuide />
        </section>
      </div>
    </div>
  );
}
