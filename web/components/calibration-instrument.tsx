import { formatUtc, relativeTime } from "@/lib/format";
import type {
  CalibrationHealthResponse,
  CalibrationPosition,
} from "@/lib/trace-api";

/** The visible slice of the kappa axis. Kappa runs from -1 to 1 in
 * principle. The thresholds all sit between 0.4 and 0.65, so the scale is
 * zoomed to where the decisions are, and says so. */
const SCALE_MIN = 0.25;
const SCALE_MAX = 0.75;

function pct(value: number): number {
  const clamped = Math.min(SCALE_MAX, Math.max(SCALE_MIN, value));
  return ((clamped - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100;
}

const POSITION_TEXT: Record<
  CalibrationPosition,
  { tone: string; headline: string }
> = {
  at_or_above_recovery: {
    tone: "text-positive",
    headline: "At or above the recovery threshold",
  },
  between_thresholds: {
    tone: "text-warning",
    headline: "Between the entry and recovery thresholds",
  },
  at_or_below_entry: {
    tone: "text-failure",
    headline: "At or below the drift entry threshold",
  },
  insufficient_data: {
    tone: "text-text-secondary",
    headline: "Not enough labeled rows to place a reading",
  },
};

function interpretation(health: CalibrationHealthResponse): string {
  const { drift_entry_threshold: entry, recovery_threshold: recovery } = health;
  switch (health.position) {
    case "between_thresholds":
      return `Kappa is above the drift entry line at ${entry.toFixed(2)} and still below the ${recovery.toFixed(2)} needed to count as recovered. The two thresholds differ on purpose, so a reading cannot flip the state by crossing a single value.`;
    case "at_or_below_entry":
      return `Kappa is at or below ${entry.toFixed(2)}, the drift entry line. The judge agrees with the labels noticeably less than its baseline.`;
    case "at_or_above_recovery":
      return `Kappa is at or above the ${recovery.toFixed(2)} recovery line.`;
    case "insufficient_data":
      return `Fewer than ${health.min_n} labeled rows were scored, which is the minimum for a reading.`;
  }
}

function Marker({
  at,
  label,
  value,
  side,
  align = "center",
}: {
  at: number;
  label: string;
  value: number;
  side: "above" | "below";
  align?: "center" | "start" | "end";
}) {
  const translate =
    align === "center"
      ? "-translate-x-1/2"
      : align === "end"
        ? "-translate-x-full"
        : "";
  return (
    <div
      className={`absolute ${translate} ${side === "below" ? "top-full pt-2" : "bottom-full pb-2"}`}
      style={{ left: `${pct(at)}%` }}
    >
      <p className="text-text-secondary text-xs whitespace-nowrap">{label}</p>
      <p className="tabular-metric text-text-primary text-sm">
        {value.toFixed(value === 0.605 ? 3 : 2)}
      </p>
    </div>
  );
}

/**
 * The persisted calibration reading drawn against its policy: the drift
 * entry line, the recovery line and the healthy baseline, with the one real
 * kappa on the same axis. It is one point in time. There is no trend line
 * because only one reading exists on record.
 */
export function CalibrationInstrument({
  health,
}: {
  health: CalibrationHealthResponse | null;
}) {
  if (!health) {
    return (
      <section id="calibration" aria-labelledby="calibration-heading">
        <h2
          id="calibration-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Calibration
        </h2>
        <p className="border-failure/40 bg-failure/5 text-text-primary mt-6 rounded-lg border p-5 text-base">
          The calibration reading is not available. The gateway did not return
          it, so no state is shown instead of a guess.
        </p>
      </section>
    );
  }

  const text = POSITION_TEXT[health.position];
  const entry = health.drift_entry_threshold;
  const recovery = health.recovery_threshold;

  return (
    <section id="calibration" aria-labelledby="calibration-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="calibration-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Calibration
        </h2>
        <p className="text-text-tertiary text-sm">
          Judge: <span className="font-mono">{health.judge_id}</span> (frontier
          tier). The flash judge is not calibrated.
        </p>
      </div>

      <div className="mt-8 grid gap-x-16 gap-y-10 lg:grid-cols-[18rem_1fr]">
        <div>
          <p className="eyebrow">Cohen&rsquo;s kappa</p>
          <p className="tabular-metric text-text-primary mt-2 text-6xl font-semibold tracking-tight">
            {health.kappa !== null ? health.kappa.toFixed(3) : "n/a"}
          </p>
          <p className={`mt-3 text-base font-medium ${text.tone}`}>
            {health.state ? `State: ${health.state}` : "No state recorded"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {health.window_n !== null
              ? `${health.window_n} labeled rows scored (minimum ${health.min_n})`
              : `Minimum ${health.min_n} labeled rows`}
          </p>
        </div>

        <div>
          {health.kappa !== null ? (
            <div
              role="img"
              aria-label={`Kappa ${health.kappa.toFixed(3)} on a scale from ${SCALE_MIN} to ${SCALE_MAX}. Drift entry threshold ${entry.toFixed(2)}, recovery threshold ${recovery.toFixed(2)}, healthy baseline ${health.healthy_baseline_kappa.toFixed(3)}.`}
              className="relative mt-16 mb-20 h-3"
            >
              <div className="bg-surface absolute inset-0 overflow-hidden rounded-full">
                <div
                  className="bg-failure/35 absolute inset-y-0 left-0"
                  style={{ width: `${pct(entry)}%` }}
                />
                <div
                  className="bg-warning/35 absolute inset-y-0"
                  style={{
                    left: `${pct(entry)}%`,
                    width: `${pct(recovery) - pct(entry)}%`,
                  }}
                />
                <div
                  className="bg-positive/30 absolute inset-y-0 right-0"
                  style={{ left: `${pct(recovery)}%` }}
                />
              </div>

              {[entry, recovery].map((t) => (
                <span
                  key={t}
                  aria-hidden="true"
                  className="bg-text-secondary absolute -top-1 h-5 w-px"
                  style={{ left: `${pct(t)}%` }}
                />
              ))}
              <span
                aria-hidden="true"
                className="border-text-tertiary absolute -top-1 h-5 border-l border-dashed"
                style={{ left: `${pct(health.healthy_baseline_kappa)}%` }}
              />

              <Marker
                at={entry}
                label="Drift entry"
                value={entry}
                side="below"
                align="end"
              />
              <Marker
                at={recovery}
                label="Recovery"
                value={recovery}
                side="below"
              />
              <Marker
                at={health.healthy_baseline_kappa}
                label="Healthy baseline"
                value={health.healthy_baseline_kappa}
                side="below"
                align="start"
              />

              <div
                className="absolute bottom-full -translate-x-1/2 pb-1.5"
                style={{ left: `${pct(health.kappa)}%` }}
              >
                <p className="tabular-metric text-text-primary text-sm font-semibold whitespace-nowrap">
                  kappa {health.kappa.toFixed(3)}
                </p>
              </div>
              <span
                aria-hidden="true"
                className="bg-text-primary border-background absolute top-1/2 h-6 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                style={{ left: `${pct(health.kappa)}%` }}
              />
              <div className="text-text-tertiary absolute top-full right-0 left-0 mt-14 flex justify-between font-mono text-[11px]">
                <span>{SCALE_MIN.toFixed(2)}</span>
                <span>
                  scale {SCALE_MIN.toFixed(2)} to {SCALE_MAX.toFixed(2)}, not
                  the full kappa range
                </span>
                <span>{SCALE_MAX.toFixed(2)}</span>
              </div>
            </div>
          ) : null}

          <p className={`text-lg font-medium ${text.tone}`}>{text.headline}</p>
          <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
            {interpretation(health)}
          </p>
        </div>
      </div>

      <dl className="border-border mt-10 grid gap-x-10 gap-y-4 border-t pt-6 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-text-tertiary">Persisted</dt>
        <dd className="text-text-secondary">
          {health.state_as_of
            ? `${formatUtc(health.state_as_of)}, ${relativeTime(health.state_as_of)}`
            : "No timestamp recorded"}
        </dd>
        <dt className="text-text-tertiary">Provenance</dt>
        <dd className="text-text-secondary max-w-3xl">
          One manual canary run read from a file on disk. It is not a scheduled
          or continuously running monitor, and no earlier readings are
          persisted, so there is no trend to draw. The service reports: &ldquo;
          {health.note}&rdquo;
        </dd>
      </dl>
    </section>
  );
}
