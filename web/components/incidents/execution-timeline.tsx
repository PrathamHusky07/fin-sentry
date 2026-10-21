import {
  HypothesisStatusBadge,
  QueryOutcomeBadge,
  SubsystemChip,
} from "@/components/incidents/badges";
import { formatUtcSeconds } from "@/lib/format";
import {
  STOPPING_LABEL,
  formatArgs,
  queryOutcome,
  timelineSteps,
  type Assessed,
  type Detail,
  type PlanFailed,
  type PlanMade,
  type QueryRun,
  type Step,
  type Stopped,
} from "@/lib/incidents";

const MAX_FACTS = 10;

function Node({
  tone,
  children,
  id,
}: {
  tone: string;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <li id={id} className="relative scroll-mt-32 pb-8 pl-8 last:pb-0">
      <span
        aria-hidden="true"
        className="absolute top-2 -left-[5px] h-2.5 w-2.5 rounded-full border-2"
        style={{ borderColor: tone, background: "var(--background)" }}
      />
      {children}
    </li>
  );
}

function When({ at }: { at: string }) {
  return (
    <span className="text-text-tertiary tabular-metric text-xs">
      {formatUtcSeconds(at).split(", ")[1]} UTC
    </span>
  );
}

function Facts({ q }: { q: QueryRun }) {
  const entries = Object.entries(q.records);
  if (entries.length === 0) return null;
  return (
    <details className="group mt-2">
      <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline-offset-4 group-open:underline">
        What it returned ({entries.length}{" "}
        {entries.length === 1 ? "record" : "records"})
      </summary>
      <ul className="border-border mt-1 divide-y divide-[var(--border)] rounded-lg border">
        {entries.slice(0, MAX_FACTS).map(([key, facts]) => (
          <li key={key} className="px-3 py-2">
            <span className="text-text-primary font-mono text-xs break-all">
              {key}
            </span>
            <span className="text-text-secondary mt-0.5 block font-mono text-xs break-words">
              {Object.entries(facts)
                .filter(([, v]) => v !== null && v !== "")
                .map(([k, v]) => `${k}: ${String(v)}`)
                .join("   ")}
            </span>
          </li>
        ))}
        {entries.length > MAX_FACTS ? (
          <li className="text-text-tertiary px-3 py-2 text-sm">
            {entries.length - MAX_FACTS} more records are cited by id in the
            evidence section when the report uses them.
          </li>
        ) : null}
      </ul>
    </details>
  );
}

function resultText(q: QueryRun): string {
  switch (queryOutcome(q)) {
    case "returned": {
      const n = Object.keys(q.records).length;
      return `${n} ${n === 1 ? "record" : "records"} came back.`;
    }
    case "verified_empty":
      return "The tool ran and matched nothing. That is a real absence for this query.";
    case "unverified_empty":
      return "The tool returned nothing, and this transport cannot tell no rows from a failed query. It is not read as an absence.";
    case "unavailable":
      return "The tool could not run, so this query says nothing about the platform. It is not an empty result.";
    case "rejected":
      return "The tool refused the arguments. The query was not retried.";
  }
}

function QueryStep({
  q,
  at,
  opening,
}: {
  q: QueryRun;
  at: string;
  opening: boolean;
}) {
  const purpose = q.retry_justification
    ? `Retried, because ${q.retry_justification}.`
    : q.separates.length > 0
      ? `Chosen to tell ${q.separates.join(" and ")} apart.`
      : opening
        ? "Opened the investigation from its trigger."
        : "Read as the source of a later query.";
  return (
    <Node tone="var(--text-secondary)" id={q.query_id}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary font-mono text-base font-semibold">
          {q.query_id}
        </span>
        <span className="text-text-primary font-mono text-sm">{q.tool}</span>
        <QueryOutcomeBadge outcome={queryOutcome(q)} />
        <When at={at} />
      </div>
      <p className="text-text-tertiary mt-1 font-mono text-xs break-words">
        {formatArgs(q.args)}
      </p>
      <p className="text-text-secondary mt-2 text-base leading-relaxed">
        {purpose}
      </p>
      <p className="text-text-primary mt-1 text-base leading-relaxed">
        {resultText(q)}
      </p>
      {q.error ? (
        <p className="border-failure/30 text-text-secondary mt-2 rounded-md border border-dashed p-2 font-mono text-xs break-words">
          {q.error}
        </p>
      ) : null}
      <Facts q={q} />
    </Node>
  );
}

function PlanStep({ p, at }: { p: PlanMade; at: string }) {
  return (
    <Node tone="var(--accent)">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary text-base font-semibold">
          Planning round {p.round}
        </span>
        <span className="text-text-tertiary font-mono text-xs break-all">
          {p.planner}
        </span>
        <When at={at} />
      </div>
      <p className="text-text-secondary mt-2 text-base leading-relaxed">
        The planner proposed {p.hypotheses.length} competing hypotheses with
        structured predictions. Validation kept {p.queries_kept}{" "}
        {p.queries_kept === 1 ? "query" : "queries"} that tell hypotheses apart.
      </p>
      <ul className="mt-3 space-y-2">
        {p.hypotheses.map((h) => (
          <li
            key={h.hypothesis_id}
            className="border-border rounded-lg border p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-text-tertiary font-mono text-sm">
                {h.hypothesis_id}
              </span>
              <SubsystemChip subsystem={h.subsystem} />
              <span className="text-text-tertiary text-sm">
                {h.predictions.length}{" "}
                {h.predictions.length === 1 ? "prediction" : "predictions"}{" "}
                about {h.symptom.replace(/_/g, " ")}
              </span>
            </div>
            <p className="text-text-primary mt-1.5 text-base leading-relaxed">
              {h.statement}
            </p>
          </li>
        ))}
      </ul>
      {p.notes.length > 0 ? (
        <details className="group mt-2">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline-offset-4 group-open:underline">
            What validation dropped ({p.notes.length})
          </summary>
          <ul className="text-text-secondary mt-1 list-disc space-y-1 pl-5 text-base">
            {p.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </Node>
  );
}

function PlanFailedStep({ p, at }: { p: PlanFailed; at: string }) {
  return (
    <Node tone="var(--warning)">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary text-base font-semibold">
          Planning round {p.round}, attempt {p.attempt}, produced no plan
        </span>
        <When at={at} />
      </div>
      <p className="border-warning/40 text-text-secondary mt-2 rounded-md border border-dashed p-3 font-mono text-xs break-words">
        {p.error}
      </p>
    </Node>
  );
}

const DECISION: Record<Assessed["decision"], string> = {
  diagnose:
    "Decision: report the leader. A leading hypothesis met every prediction it made and no rival is also supported.",
  abstain:
    "Decision: abstain. The retrieved records do not support a root cause and no budget was left to look further.",
  continue:
    "Decision: continue. The evidence did not settle it and budget remained, so the investigator asked for a second look.",
};

function AssessmentStep({
  step,
}: {
  step: Step & { entry: { event: Assessed } };
}) {
  const a = step.entry.event;
  return (
    <Node tone="var(--info)">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary text-base font-semibold">
          Hypotheses updated after round {a.round}
        </span>
        <When at={step.entry.at} />
      </div>
      <ul className="mt-2 space-y-1.5">
        {step.changes.length === 0 ? (
          <li className="text-text-secondary text-base">
            No hypothesis changed status.
          </li>
        ) : (
          step.changes.map((c) => (
            <li
              key={c.hypothesis_id}
              className="flex flex-wrap items-center gap-2 text-base"
            >
              <span className="text-text-primary font-mono">
                {c.hypothesis_id}
              </span>
              <span className="text-text-tertiary">
                {c.from ? "" : "first assessed as"}
              </span>
              {c.from ? <HypothesisStatusBadge status={c.from} /> : null}
              {c.from ? <span aria-hidden="true">→</span> : null}
              <HypothesisStatusBadge status={c.to} />
            </li>
          ))
        )}
      </ul>
      <p className="text-text-primary mt-3 text-base leading-relaxed">
        {DECISION[a.decision]}
      </p>
      {a.notes.length > 0 ? (
        <p className="text-text-secondary mt-1 text-base leading-relaxed">
          {a.notes[0]}
        </p>
      ) : null}
      {a.decision !== "diagnose" && a.unresolved.length > 0 ? (
        <details className="group mt-1">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline-offset-4 group-open:underline">
            What was still unresolved ({a.unresolved.length})
          </summary>
          <ul className="text-text-secondary mt-1 list-disc space-y-1 pl-5 text-base">
            {a.unresolved.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </Node>
  );
}

function StoppedStep({ s, at }: { s: Stopped; at: string }) {
  return (
    <Node tone="var(--text-primary)">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary text-base font-semibold">
          Stopped: {STOPPING_LABEL[s.stopping_reason]}
        </span>
        <When at={at} />
      </div>
      <p className="text-text-secondary mt-1 text-base leading-relaxed">
        {s.why}
      </p>
    </Node>
  );
}

/** Every step the loop stored, in order: each query with its tool outcome, each planning
 * round, each ledger update with the status changes it caused, and the stop. The investigator
 * stores structured events, not reasoning text, so none is shown. */
export function ExecutionTimeline({ detail }: { detail: Detail }) {
  const steps = timelineSteps(detail);
  const firstQuery = steps.findIndex((s) => s.entry.event.kind === "query");
  return (
    <section
      id="timeline"
      aria-labelledby="timeline-heading"
      className="scroll-mt-32"
    >
      <h2
        id="timeline-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Decision trail
      </h2>
      <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed">
        What the investigator did, in order. Each query says which hypotheses it
        was chosen to tell apart and what the tool actually returned.
      </p>
      {steps.length === 0 ? (
        <p className="border-border-strong text-text-secondary mt-4 rounded-xl border border-dashed px-5 py-8 text-base">
          No event was stored for this session.
        </p>
      ) : (
        <ol className="border-border-strong mt-6 ml-1 border-l">
          {steps.map((step, i) => {
            const { event, at, seq } = step.entry;
            switch (event.kind) {
              case "query":
                return (
                  <QueryStep
                    key={seq}
                    q={event}
                    at={at}
                    opening={i === firstQuery}
                  />
                );
              case "plan":
                return <PlanStep key={seq} p={event} at={at} />;
              case "plan_failed":
                return <PlanFailedStep key={seq} p={event} at={at} />;
              case "assessment":
                return (
                  <AssessmentStep
                    key={seq}
                    step={step as Step & { entry: { event: Assessed } }}
                  />
                );
              case "stopped":
                return <StoppedStep key={seq} s={event} at={at} />;
            }
          })}
        </ol>
      )}
    </section>
  );
}
