import { describe, expect, it } from "vitest";
import { buildAttentionItems } from "@/lib/attention";
import type { OverviewData } from "@/lib/overview-data";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

const QUIET_OVERVIEW: OverviewData = {
  totalRequests: 20,
  scanIsWindow: false,
  disagreementIsWindow: false,
  latestTimestamp: "2026-01-01T00:00:00.000Z",
  judgeStateCounts: {
    evaluated: 20,
    partially_evaluated: 0,
    blocked_before_evaluation: 0,
    judge_failed: 0,
    never_evaluated: 0,
  },
  flow: {
    total: 20,
    stoppedAt: { input: 0, retrieval: 0, output: 0, unknown: 0 },
    errored: 0,
    delivered: 20,
    deliveredComplete: 20,
    deliveredPartial: 0,
    deliveredUnjudged: 0,
    deliveredJudgeFailed: 0,
  },
  frontierSampledCount: 2,
  blockedTotal: 0,
  blockedByReason: [],
  errorCount: 0,
  disagreementTraces: [],
};

const HEALTHY_CALIBRATION: CalibrationHealthResponse = {
  judge_id: "gemini-rubric",
  kappa: 0.6,
  state: "healthy",
  window_n: 100,
  min_n: 30,
  healthy_baseline_kappa: 0.6,
  drift_entry_threshold: 0.5,
  recovery_threshold: 0.54,
  position: "at_or_above_recovery",
  state_as_of: "2026-01-01T00:00:00.000Z",
  note: "",
};

describe("buildAttentionItems calibration handling", () => {
  it("raises an explicit unavailable item when overview loads but calibration does not", () => {
    const items = buildAttentionItems({
      overview: QUIET_OVERVIEW,
      calibration: null,
      disagreementDetails: [],
    });
    expect(items).toHaveLength(1);
    expect(items[0].key).toBe("calibration-unavailable");
    expect(items[0].title).toBe("Calibration unavailable");
    expect(items[0].tone).toBe("warning");
  });

  it("is empty only when every source loaded and nothing fired", () => {
    const items = buildAttentionItems({
      overview: QUIET_OVERVIEW,
      calibration: HEALTHY_CALIBRATION,
      disagreementDetails: [],
    });
    expect(items).toEqual([]);
  });

  it("does not raise the unavailable item when calibration is present", () => {
    const items = buildAttentionItems({
      overview: QUIET_OVERVIEW,
      calibration: { ...HEALTHY_CALIBRATION, position: "between_thresholds" },
      disagreementDetails: [],
    });
    expect(items.map((i) => i.key)).toEqual(["calibration"]);
  });
});
