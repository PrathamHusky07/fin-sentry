import type { CalibrationHealthResponse } from "@/lib/trace-api";

/**
 * Where the frontier judge’s agreement with labeled data sits against the
 * thresholds that decide its state. The zones are the real state machine
 * (drift below the entry line, recovered above the recovery line, a gap
 * between them), the ticks are persisted thresholds, and the dot is the
 * last persisted reading. The axis is cropped to the region that holds
 * those numbers and its end values are printed.
 */
export function CalibrationScale({
  calibration,
}: {
  calibration: CalibrationHealthResponse;
}) {
  const { kappa, drift_entry_threshold: entry } = calibration;
  const recovery = calibration.recovery_threshold;
  const baseline = calibration.healthy_baseline_kappa;
  const lo = Math.min(0.3, entry - 0.1, kappa ?? 1);
  const hi = Math.max(0.7, baseline + 0.08, kappa ?? 0);
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const width = (a: number, b: number) => `${((b - a) / (hi - lo)) * 100}%`;

  return (
    <div
      role="img"
      aria-label={`Cohen’s kappa ${kappa !== null ? kappa.toFixed(3) : "unavailable"}. Drift begins at ${entry.toFixed(2)}, recovery at ${recovery.toFixed(2)}, healthy baseline ${baseline.toFixed(3)}.`}
      className="relative mx-2 mt-9 mb-9 h-3"
    >
      <span
        className="bg-failure/30 absolute inset-y-0 rounded-l-full"
        style={{ left: 0, width: width(lo, entry) }}
      />
      <span
        className="bg-warning/30 absolute inset-y-0"
        style={{ left: at(entry), width: width(entry, recovery) }}
      />
      <span
        className="bg-positive/30 absolute inset-y-0 rounded-r-full"
        style={{ left: at(recovery), width: width(recovery, hi) }}
      />

      {[
        { v: entry, label: `${entry.toFixed(2)} drift`, up: false },
        { v: recovery, label: `${recovery.toFixed(2)} recovery`, up: false },
        { v: baseline, label: `${baseline.toFixed(3)} healthy`, up: true },
      ].map((tick) => (
        <span
          key={tick.label}
          className="absolute"
          style={{ left: at(tick.v) }}
        >
          <span
            className={`bg-text-tertiary absolute h-5 w-px -translate-x-1/2 ${tick.up ? "-top-4" : "-top-1"}`}
          />
          <span
            className={`text-text-tertiary absolute -translate-x-1/2 font-mono text-[11px] whitespace-nowrap ${tick.up ? "-top-9" : "top-5"}`}
          >
            {tick.label}
          </span>
        </span>
      ))}

      {kappa !== null ? (
        <span className="absolute top-1/2" style={{ left: at(kappa) }}>
          <span className="bg-text-primary border-background absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2" />
        </span>
      ) : null}
    </div>
  );
}
