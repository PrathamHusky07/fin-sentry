import { QueryOutcomeBadge } from "@/components/incidents/badges";
import {
  formatArgs,
  queryOutcome,
  type Detail,
  type ProposedVerification,
  type QueryRun,
} from "@/lib/incidents";

function queries(d: Detail): QueryRun[] {
  return d.timeline.flatMap((t) => (t.event.kind === "query" ? [t.event] : []));
}

function Group({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-text-primary text-lg font-semibold">{title}</h3>
      <div className="mt-2 space-y-2">{children}</div>
    </div>
  );
}

function QueryLine({ q }: { q: QueryRun }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <a
        href={`#${q.query_id}`}
        className="text-accent inline-flex min-h-11 min-w-11 items-center justify-center font-mono text-sm underline underline-offset-4"
      >
        {q.query_id}
      </a>
      <span className="text-text-primary font-mono text-sm">{q.tool}</span>
      <QueryOutcomeBadge outcome={queryOutcome(q)} />
      <span className="text-text-tertiary font-mono text-xs break-words">
        {formatArgs(q.args)}
      </span>
    </li>
  );
}

function verificationText(v: ProposedVerification): string {
  switch (v.kind) {
    case "red_team_scenario":
      return `Run the Red Team scenario ${v.scenario_id} against the defense in question and compare the result with the incident.`;
    case "read_only_query":
      return `Run one more read-only query: ${v.tool} with ${v.args ? formatArgs(v.args) : "no arguments"}.`;
    case "none_available":
      return "No further safe read-only step is on offer.";
  }
}

/** What the investigation could not establish, kept apart from what cut against a hypothesis.
 * An unavailable source, a verified empty result and an empty result nobody could verify are
 * three different facts and are listed separately. The one proposed verification is shown as
 * proposed and never run, because this investigation has no tool that runs anything. */
export function NotEstablished({ detail: d }: { detail: Detail }) {
  const report = d.report;
  const ran = queries(d);
  const unavailable = ran.filter((q) => queryOutcome(q) === "unavailable");
  const verifiedEmpty = ran.filter((q) => queryOutcome(q) === "verified_empty");
  const unverified = ran.filter((q) => queryOutcome(q) === "unverified_empty");
  const missing =
    report?.missing_evidence ?? d.state?.unresolved_questions ?? [];
  const gaps = d.state?.known_data_gaps ?? [];
  return (
    <section id="gaps" aria-labelledby="gaps-heading" className="scroll-mt-32">
      <h2
        id="gaps-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        What was not established
      </h2>
      <div className="mt-6 grid gap-10 lg:grid-cols-2">
        <div className="space-y-8">
          <Group title="Missing evidence">
            {report || d.state ? (
              missing.length > 0 ? (
                <ul className="text-text-secondary list-disc space-y-1.5 pl-5 text-base leading-relaxed">
                  {missing.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-text-secondary text-base">
                  The investigator recorded no open question.
                </p>
              )
            ) : (
              <p className="text-text-secondary text-base">
                Not stored. This session ended without a report or a final
                state.
              </p>
            )}
          </Group>

          <Group title="Queries that did not give an answer">
            {ran.length === 0 ? (
              <p className="text-text-secondary text-base">
                No query was stored.
              </p>
            ) : unavailable.length +
                verifiedEmpty.length +
                unverified.length ===
              0 ? (
              <p className="text-text-secondary text-base">
                Every query that ran returned records.
              </p>
            ) : (
              <ul className="space-y-1">
                {[...unavailable, ...unverified, ...verifiedEmpty].map((q) => (
                  <QueryLine key={q.query_id} q={q} />
                ))}
              </ul>
            )}
            {unavailable.length > 0 ? (
              <p className="text-text-secondary text-base leading-relaxed">
                A source that could not run says nothing about the platform. It
                is never counted as an empty result or as a clean reading.
              </p>
            ) : null}
          </Group>
        </div>

        <div className="space-y-8">
          <Group title="Proposed verification, not run">
            {report ? (
              <div className="border-border-strong rounded-xl border border-dashed p-5">
                <p className="text-text-primary text-base leading-relaxed">
                  {verificationText(report.proposed_verification)}
                </p>
                <p className="text-text-secondary mt-2 text-base leading-relaxed">
                  {report.proposed_verification.rationale}
                </p>
                <p className="text-text-tertiary mt-3 text-sm">
                  Proposed only. This investigation has no tool that runs
                  anything, so the step was never executed.
                </p>
              </div>
            ) : (
              <p className="text-text-secondary text-base">
                No report was stored, so no verification was proposed.
              </p>
            )}
          </Group>

          {report && report.limitations.length > 0 ? (
            <details className="group">
              <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline-offset-4 group-open:underline">
                Limitations the investigator recorded (
                {report.limitations.length})
              </summary>
              <ul className="text-text-secondary mt-1 list-disc space-y-2 pl-5 text-base leading-relaxed">
                {report.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </details>
          ) : gaps.length > 0 ? (
            <details className="group">
              <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline-offset-4 group-open:underline">
                What this investigator cannot see ({gaps.length})
              </summary>
              <ul className="text-text-secondary mt-1 list-disc space-y-2 pl-5 text-base leading-relaxed">
                {gaps.map((g) => (
                  <li key={g.source + g.detail}>
                    <span className="text-text-primary font-mono text-sm">
                      {g.source}
                    </span>
                    {": "}
                    {g.detail}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </div>
    </section>
  );
}
