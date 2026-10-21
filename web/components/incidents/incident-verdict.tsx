import { ConfidenceChip, SubsystemChip } from "@/components/incidents/badges";
import { stoppedWhy } from "@/lib/agent-view";
import {
  STOPPING_LABEL,
  STOPPING_MEANING,
  hypothesisRows,
  type Detail,
} from "@/lib/incidents";

function Panel({
  tone,
  title,
  children,
}: {
  tone: "info" | "neutral" | "failure" | "warning" | "accent";
  title: string;
  children: React.ReactNode;
}) {
  const style = {
    info: "border-info/40 bg-info/5",
    neutral: "border-border-strong bg-surface",
    failure: "border-failure/40 bg-failure/5",
    warning: "border-warning/50 border-dashed bg-warning/5",
    accent: "border-accent/40 bg-accent/5",
  }[tone];
  return (
    <section
      aria-labelledby="verdict-heading"
      className={`rounded-xl border p-5 sm:p-7 ${style}`}
    >
      <h2 id="verdict-heading" className="eyebrow">
        {title}
      </h2>
      <div className="mt-3 space-y-4">{children}</div>
    </section>
  );
}

function Stop({ d }: { d: Detail }) {
  if (!d.stopping_reason) return null;
  const why = stoppedWhy(d);
  return (
    <div className="border-border border-t pt-4">
      <p className="text-text-primary text-base font-medium">
        Stopped: {STOPPING_LABEL[d.stopping_reason]}
      </p>
      <p className="text-text-secondary mt-1 text-base leading-relaxed">
        {STOPPING_MEANING[d.stopping_reason]}
      </p>
      {why ? (
        <p className="text-text-secondary mt-2 text-base leading-relaxed">
          The investigator recorded: {why}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The outcome, stated for what it is. A diagnosis is the best-supported hypothesis and
 * carries its own limit in the same panel. An abstention is a complete result and is not
 * styled as a failure. A failed or interrupted session says so and shows only what it kept.
 */
export function IncidentVerdict({ detail: d }: { detail: Detail }) {
  if (d.status === "running") {
    return (
      <Panel tone="accent" title="Outcome">
        <p className="text-text-primary text-lg">
          No outcome yet. The investigation has not stopped.
        </p>
        <p className="text-text-secondary text-base leading-relaxed">
          The timeline below shows each query as it was stored.
        </p>
      </Panel>
    );
  }
  if (d.status === "failed") {
    return (
      <Panel tone="failure" title="Outcome: the investigation failed">
        <p className="text-text-primary text-lg">
          The investigator raised an error before it produced a report.
        </p>
        <p className="border-failure/30 text-text-primary rounded-md border border-dashed p-3 font-mono text-sm break-words">
          {d.error}
        </p>
        <p className="text-text-secondary text-base leading-relaxed">
          No conclusion was reached, so none is shown. The queries it ran, the
          hypotheses it held and the spend are kept below exactly as stored.
        </p>
      </Panel>
    );
  }
  if (d.status === "interrupted") {
    return (
      <Panel tone="warning" title="Outcome: the investigation was interrupted">
        <p className="text-text-primary text-lg">No conclusion was reached.</p>
        <p className="text-text-secondary text-base leading-relaxed">
          {d.error}
        </p>
        <p className="text-text-secondary text-base leading-relaxed">
          Nothing here is a conclusion. The events stored before it stopped are
          shown below, and a new investigation is the only way to look again.
        </p>
      </Panel>
    );
  }
  const report = d.report;
  if (!report) {
    return (
      <Panel tone="warning" title="Outcome">
        <p className="text-text-primary text-lg">
          This session is marked completed but stored no report.
        </p>
      </Panel>
    );
  }
  if (report.outcome === "abstention") {
    return (
      <Panel tone="neutral" title="Outcome: no root cause was established">
        <p className="text-text-primary text-xl leading-snug text-balance">
          {report.abstention_statement}
        </p>
        <p className="text-text-secondary text-base leading-relaxed">
          This is a complete result. The investigator looked, found that the
          retrieved records did not support a cause, and said so instead of
          choosing one.
        </p>
        {report.missing_evidence.length > 0 ? (
          <div>
            <p className="text-text-tertiary text-sm">
              What was not established
            </p>
            <ul className="text-text-secondary mt-1 list-disc space-y-1 pl-5 text-base">
              {report.missing_evidence.slice(0, 3).map((m, i) => (
                <li key={i}>{m}</li>
              ))}
              {report.missing_evidence.length > 3 ? (
                <li>
                  <a
                    href="#gaps"
                    className="text-accent underline underline-offset-4"
                  >
                    {report.missing_evidence.length - 3} more below
                  </a>
                </li>
              ) : null}
            </ul>
          </div>
        ) : null}
        <Stop d={d} />
      </Panel>
    );
  }
  const lead = hypothesisRows(d).find((r) => r.rank === 1);
  const refuted = hypothesisRows(d).filter(
    (r) => r.status === "refuted",
  ).length;
  return (
    <Panel
      tone="info"
      title="Outcome: best-supported hypothesis, not a proven cause"
    >
      {lead ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <SubsystemChip subsystem={lead.subsystem} />
            {lead.confidence ? (
              <ConfidenceChip confidence={lead.confidence} />
            ) : null}
          </div>
          <p className="text-text-primary text-xl leading-snug text-balance">
            {lead.statement}
          </p>
        </>
      ) : null}
      <p className="text-text-secondary text-base leading-relaxed">
        The records below are consistent with this hypothesis. It was checked
        against its own predictions and against the counter-evidence the
        investigator retrieved. That check does not prove the cause, and the
        stored records cannot establish what caused the incident.
      </p>
      <dl className="grid gap-4 sm:grid-cols-3">
        <div>
          <dt className="text-text-tertiary text-sm">Records supporting it</dt>
          <dd className="tabular-metric text-text-primary text-2xl">
            {lead?.supporting.filter((r) => r.kind !== "query_result").length ??
              0}
          </dd>
        </div>
        <div>
          <dt className="text-text-tertiary text-sm">
            Rivals refuted by a record
          </dt>
          <dd className="tabular-metric text-text-primary text-2xl">
            {refuted}
          </dd>
        </div>
        <div>
          <dt className="text-text-tertiary text-sm">Left unestablished</dt>
          <dd className="tabular-metric text-text-primary text-2xl">
            {report.missing_evidence.length}
          </dd>
        </div>
      </dl>
      <Stop d={d} />
    </Panel>
  );
}
