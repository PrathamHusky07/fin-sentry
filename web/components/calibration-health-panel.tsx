import type { CalibrationHealthResponse } from "@/lib/trace-api";

const POSITION_LABEL: Record<CalibrationHealthResponse["position"], string> = {
  at_or_above_recovery: "At or above the recovery threshold",
  between_thresholds: "Between the entry and recovery thresholds",
  at_or_below_entry: "At or below the drift entry threshold",
  insufficient_data: "Insufficient data",
};

const POSITION_COLOR: Record<CalibrationHealthResponse["position"], string> = {
  at_or_above_recovery: "text-positive",
  between_thresholds: "text-warning",
  at_or_below_entry: "text-failure",
  insufficient_data: "text-text-secondary",
};

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value * 100));
}

/**
 * Current position against the Day 6 DriftConfig thresholds -- a single
 * point-in-time panel, never a trend chart. Only one real historical kappa
 * observation exists on disk (see ../CLAUDE.md), so there is nothing to
 * plot a series from yet.
 */
export function CalibrationHealthPanel({
  health,
}: {
  health: CalibrationHealthResponse;
}) {
  const hasKappa = health.kappa !== null;

  return (
    <div className="border-border bg-background-elevated rounded-md border p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-text-primary text-sm font-semibold">
          Calibration health — {health.judge_id}
        </h2>
        <span
          className={`text-sm font-medium ${POSITION_COLOR[health.position]}`}
        >
          {POSITION_LABEL[health.position]}
        </span>
      </div>

      <div className="mt-4 flex items-baseline gap-3">
        <span className="tabular-metric text-text-primary text-2xl font-semibold">
          {hasKappa ? health.kappa!.toFixed(3) : "—"}
        </span>
        <span className="text-text-secondary text-xs">
          {health.state ? `state: ${health.state}` : "no state recorded"}
          {health.window_n !== null ? ` · n=${health.window_n}` : ""}
        </span>
      </div>

      {hasKappa ? (
        <div className="relative mt-4 h-2 rounded-full bg-[color-mix(in_srgb,var(--text-secondary)_20%,transparent)]">
          <div
            className="bg-failure/30 absolute h-full rounded-l-full"
            style={{ width: `${clampPercent(health.drift_entry_threshold)}%` }}
          />
          <div
            className="bg-warning/30 absolute h-full"
            style={{
              left: `${clampPercent(health.drift_entry_threshold)}%`,
              width: `${clampPercent(health.recovery_threshold) - clampPercent(health.drift_entry_threshold)}%`,
            }}
          />
          <div
            className="border-text-primary absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-white"
            style={{ left: `${clampPercent(health.kappa!)}%` }}
            aria-label={`current kappa ${health.kappa!.toFixed(3)}`}
          />
        </div>
      ) : null}

      <dl className="text-text-secondary mt-4 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt>Entry threshold</dt>
          <dd className="tabular-metric text-text-primary">
            {health.drift_entry_threshold.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt>Recovery threshold</dt>
          <dd className="tabular-metric text-text-primary">
            {health.recovery_threshold.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt>Healthy baseline</dt>
          <dd className="tabular-metric text-text-primary">
            {health.healthy_baseline_kappa.toFixed(3)}
          </dd>
        </div>
      </dl>

      <p className="text-text-secondary mt-3 text-xs">
        {health.state_as_of
          ? `As of ${new Date(health.state_as_of).toLocaleString()}. `
          : ""}
        {health.note}
      </p>
    </div>
  );
}
