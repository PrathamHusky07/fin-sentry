import {
  asObject,
  canarySmoke,
  numOrNull,
  strOrNull,
} from "@/lib/archive/files";
import policy from "@/lib/archive/drift-policy.json";
import type {
  CalibrationHealthResponse,
  CalibrationPosition,
} from "@/lib/trace-api";

/**
 * The calibration reading, built the way finsentry/mcp/tools/drift.py builds it: the last health
 * record in the committed canary artifact, set against the drift policy. The policy values are
 * copied into drift-policy.json, and tests/archive/test_web_archive_policy.py fails if they stop
 * matching DriftConfig. No transition history is committed, so the note says so.
 */

const NOTE =
  "reporting last-persisted state as of state_as_of; this is not a continuously running monitor. No transition-audit history is available in the persisted artifact";
const NO_READING_NOTE = "no live canary health reading has been persisted yet";

function position(kappa: number | null): CalibrationPosition {
  if (kappa === null) return "insufficient_data";
  if (kappa >= policy.recovery_threshold) return "at_or_above_recovery";
  if (kappa <= policy.drift_entry_threshold) return "at_or_below_entry";
  return "between_thresholds";
}

export async function calibrationHealth(): Promise<CalibrationHealthResponse> {
  const smoke = await canarySmoke();
  const rawHealth = smoke["health_record"];
  const health = rawHealth == null ? null : asObject(rawHealth);
  const observations = Array.isArray(smoke["observations"])
    ? smoke["observations"].map(asObject)
    : [];
  const observedAt = observations
    .map((o) => strOrNull(o, "observed_at"))
    .filter((t): t is string => t !== null);
  const kappa = health ? numOrNull(health, "kappa") : null;
  return {
    judge_id: "gemini-rubric",
    kappa,
    state: health ? strOrNull(health, "state") : null,
    window_n: health ? numOrNull(health, "window_n") : null,
    min_n: policy.min_n,
    healthy_baseline_kappa: policy.healthy_baseline_kappa,
    drift_entry_threshold: policy.drift_entry_threshold,
    recovery_threshold: policy.recovery_threshold,
    position: position(kappa),
    state_as_of:
      observedAt.length > 0
        ? observedAt.reduce((a, b) => (a > b ? a : b))
        : null,
    note: health ? NOTE : NO_READING_NOTE,
  };
}
