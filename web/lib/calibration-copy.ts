import { formatUtcDate } from "@/lib/format";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

/**
 * The one provenance sentence under the calibration reading: when it was taken, the kappa, how
 * many labeled examples it covered and where it sits against the two thresholds. Built from the
 * stored reading only, so it never states a threshold or a count the reading does not carry.
 */
export function calibrationSentence(health: CalibrationHealthResponse): string {
  const date = health.state_as_of
    ? `Last calibration: ${formatUtcDate(health.state_as_of)}. `
    : "Last calibration: date not recorded. ";
  if (health.kappa === null) {
    return `${date}No kappa reading is stored, so there is nothing to place against the thresholds.`;
  }
  const entry = health.drift_entry_threshold.toFixed(2);
  const recovery = health.recovery_threshold.toFixed(2);
  const examples =
    health.window_n !== null
      ? ` across ${health.window_n} labeled examples`
      : "";
  const was = `${date}Cohen\u2019s kappa was ${health.kappa.toFixed(3)}${examples}`;
  switch (health.position) {
    case "between_thresholds":
      return `${was}, above the drift threshold of ${entry} but below the recovery threshold of ${recovery}.`;
    case "at_or_below_entry":
      return `${was}, at or below the drift threshold of ${entry}.`;
    case "at_or_above_recovery":
      return `${was}, at or above the recovery threshold of ${recovery}.`;
    case "insufficient_data":
      return `${was}, which is too few examples to place against the thresholds of ${entry} and ${recovery}.`;
  }
}
