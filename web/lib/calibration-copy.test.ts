import { describe, expect, it } from "vitest";
import { calibrationSentence } from "@/lib/calibration-copy";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

const stored: CalibrationHealthResponse = {
  judge_id: "gemini-rubric",
  kappa: 0.5161290322580646,
  state: "degraded",
  window_n: 30,
  min_n: 30,
  healthy_baseline_kappa: 0.605,
  drift_entry_threshold: 0.43,
  recovery_threshold: 0.54,
  position: "between_thresholds",
  state_as_of: "2026-10-04T17:11:56.703109+00:00",
  note: "n/a",
};

describe("calibrationSentence", () => {
  it("states the stored reading in one plain sentence", () => {
    expect(calibrationSentence(stored)).toBe(
      "Last calibration: October 4, 2026. Cohen\u2019s kappa was 0.516 across 30 labeled examples, above the drift threshold of 0.43 but below the recovery threshold of 0.54.",
    );
  });

  it("uses the UTC date, not the viewer\u2019s", () => {
    const lateUtc = { ...stored, state_as_of: "2026-10-04T23:59:00+00:00" };
    expect(calibrationSentence(lateUtc)).toContain("October 4, 2026");
  });

  it("describes each position without borrowing another one\u2019s thresholds", () => {
    const low = calibrationSentence({
      ...stored,
      kappa: 0.4,
      position: "at_or_below_entry",
    });
    expect(low).toContain("at or below the drift threshold of 0.43.");
    expect(low).not.toContain("recovery");
    const high = calibrationSentence({
      ...stored,
      kappa: 0.6,
      position: "at_or_above_recovery",
    });
    expect(high).toContain("at or above the recovery threshold of 0.54.");
    expect(high).not.toContain("drift");
  });

  it("says so when there is no date, no count or no kappa", () => {
    expect(calibrationSentence({ ...stored, state_as_of: null })).toContain(
      "Last calibration: date not recorded.",
    );
    expect(calibrationSentence({ ...stored, window_n: null })).not.toContain(
      "labeled examples",
    );
    const none = calibrationSentence({
      ...stored,
      kappa: null,
      position: "insufficient_data",
    });
    expect(none).toContain("No kappa reading is stored");
  });
});
