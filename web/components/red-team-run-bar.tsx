import { Panel } from "@/components/panel";
import { RedTeamOutcomeBadge } from "@/components/red-team-badges";
import { shortId } from "@/lib/format";
import { runProgress, type RunDetail } from "@/lib/red-team";

const BUTTON =
  "min-h-11 rounded-lg border px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";

function RunProgress({ detail }: { detail: RunDetail }) {
  const { run } = detail;
  const { finished, total, percent } = runProgress(run);
  const heading =
    run.status === "running"
      ? "Run in progress"
      : run.status === "failed"
        ? "Run failed"
        : "Run finished";
  return (
    <Panel className="mt-4 p-4 sm:p-5" as="section">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-text-primary text-base font-medium">{heading}</h3>
        <p className="text-text-tertiary font-mono text-xs">
          Run {shortId(run.run_id)}
        </p>
      </div>
      <div
        role="progressbar"
        aria-label="Executions finished"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={finished}
        className="bg-surface mt-3 h-1.5 overflow-hidden rounded-full"
      >
        <div
          className={`h-full transition-[width] ${run.status === "failed" ? "bg-failure" : "bg-accent"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-text-secondary mt-2 text-sm">
        {finished} of {total} executions finished. Read from the stored rows
        every 1.5 seconds while the run is active.
      </p>
      {run.failure_reason ? (
        <p role="alert" className="text-failure mt-2 text-base">
          {run.failure_reason}
        </p>
      ) : null}
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {detail.executions.map((e) => (
          <li
            key={e.execution_id}
            className="border-border flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2"
          >
            <span className="text-text-primary font-mono text-sm">
              {e.scenario_id}
            </span>
            <RedTeamOutcomeBadge outcome={e.outcome} state={e.state} />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/**
 * Starts bounded runs and shows the active or latest one. One run is active
 * at a time, so every control is disabled while another run is in progress.
 * Judge-assisted scenarios are never part of "run all". They start from their
 * own row, behind a confirmation.
 */
export function RedTeamRunBar({
  deterministicCount,
  selectedCount,
  busy,
  persistenceAvailable,
  activeRun,
  startError,
  onRunAll,
  onRunSelected,
}: {
  deterministicCount: number;
  selectedCount: number;
  busy: boolean;
  persistenceAvailable: boolean;
  activeRun: RunDetail | null;
  startError: string | null;
  onRunAll: () => void;
  onRunSelected: () => void;
}) {
  const disabled = busy || !persistenceAvailable;
  return (
    <section aria-labelledby="rt-run-heading" className="mt-12">
      <h2 id="rt-run-heading" className="eyebrow">
        Run
      </h2>
      <p className="text-text-secondary mt-3 max-w-3xl text-base leading-relaxed">
        A run fires its scenarios one at a time through the live defenses and
        stores one execution per scenario. Running a scenario again stores a new
        execution and keeps the earlier one.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onRunAll}
          disabled={disabled || deterministicCount === 0}
          className={`${BUTTON} border-accent/60 bg-accent/10 text-text-primary hover:bg-accent/20`}
        >
          Run all deterministic ({deterministicCount})
        </button>
        <button
          type="button"
          onClick={onRunSelected}
          disabled={disabled || selectedCount === 0}
          className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
        >
          Run selected ({selectedCount})
        </button>
        {busy ? (
          <p role="status" className="text-text-secondary text-sm">
            A run is in progress. Controls return when it ends.
          </p>
        ) : null}
        {!persistenceAvailable ? (
          <p className="text-warning text-sm">
            Runs are disabled while the result store is unreachable.
          </p>
        ) : null}
      </div>
      {startError ? (
        <p role="alert" className="text-failure mt-3 text-base">
          {startError}
        </p>
      ) : null}
      {activeRun ? <RunProgress detail={activeRun} /> : null}
    </section>
  );
}
