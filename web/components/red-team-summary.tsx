import { Panel } from "@/components/panel";
import {
  OUTCOMES,
  OUTCOME_LABEL,
  OUTCOME_MEANING,
  type LatestSummary,
  type Outcome,
} from "@/lib/red-team";

const TONE: Record<Outcome, string> = {
  caught: "text-positive",
  missed: "text-failure",
  evaluator_unavailable: "text-warning",
  execution_failed: "text-failure",
  inconclusive: "text-text-secondary",
};

/** The one sentence a viewer reads first. It reports what the stored results
 * say and never infers that nothing is wrong from results that do not exist. */
function headline(summary: LatestSummary): string {
  if (summary.scenarioCount === 0) return "The scenario registry is empty.";
  const run = summary.scenarioCount - summary.notRun;
  if (run === 0) {
    return "No scenario has been run, so there are no results to read yet.";
  }
  const parts = [`${run} of ${summary.scenarioCount} scenarios have a result.`];
  if (summary.differs > 0) {
    parts.push(
      `${summary.differs} ${summary.differs === 1 ? "result differs" : "results differ"} from what the scenario expected.`,
    );
  }
  if (summary.gapsConfirmed > 0) {
    parts.push(
      `${summary.gapsConfirmed} known ${summary.gapsConfirmed === 1 ? "gap was" : "gaps were"} confirmed as missed.`,
    );
  }
  return parts.join(" ");
}

/**
 * DERIVED: the latest stored execution of each scenario, counted once per
 * scenario. The counts move only when a new execution is stored.
 */
export function RedTeamSummary({
  summary,
  persistenceAvailable,
}: {
  summary: LatestSummary;
  persistenceAvailable: boolean;
}) {
  return (
    <section aria-labelledby="rt-summary-heading">
      <h2 id="rt-summary-heading" className="eyebrow">
        Latest result per scenario
      </h2>
      {persistenceAvailable ? (
        <p className="text-text-primary mt-3 max-w-3xl text-lg leading-snug font-medium text-pretty">
          {headline(summary)}
        </p>
      ) : (
        <p
          role="alert"
          className="border-warning/40 bg-warning/10 text-text-primary mt-3 max-w-3xl rounded-lg border p-4 text-base"
        >
          The result store could not be read. The counts below are unknown, not
          zero.
        </p>
      )}
      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {OUTCOMES.map((outcome) => (
          <Panel key={outcome} className="p-4">
            <dt className="text-text-secondary text-sm">
              {OUTCOME_LABEL[outcome]}
            </dt>
            <dd
              className={`tabular-metric mt-1 text-3xl font-semibold ${
                persistenceAvailable ? TONE[outcome] : "text-text-tertiary"
              }`}
            >
              {persistenceAvailable ? summary.counts[outcome] : "Unknown"}
            </dd>
            <dd className="text-text-tertiary mt-1 text-xs leading-snug">
              {OUTCOME_MEANING[outcome]}
            </dd>
          </Panel>
        ))}
      </dl>
      <p className="text-text-tertiary mt-3 text-sm">
        Derived from the most recent stored execution of each scenario.
        Scenarios never run are not counted in any column.
      </p>
    </section>
  );
}
