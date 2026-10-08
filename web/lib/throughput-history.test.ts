import { describe, expect, it } from "vitest";
import type { ThroughputBucket } from "@/lib/metrics-snapshot";
import { historyRequestTotal, historyRows } from "@/lib/throughput-history";

// Shaped like the real first and last rows of the stored view: buckets weeks
// apart, so the history is sparse the way the real one is.
const BUCKETS: ThroughputBucket[] = [
  {
    window_start: "2026-09-14T22:53:00Z",
    window_end: "2026-09-14T22:54:00Z",
    total_requests: 1,
    success_count: 1,
    blocked_count: 0,
    error_count: 0,
    avg_latency_ms: 32023,
    p95_latency_ms: 31897.9,
  },
  {
    window_start: "2026-10-06T02:26:00Z",
    window_end: "2026-10-06T02:27:00Z",
    total_requests: 3,
    success_count: 2,
    blocked_count: 1,
    error_count: 0,
    avg_latency_ms: null,
    p95_latency_ms: null,
  },
];

describe("historyRows", () => {
  it("returns exactly one row per stored bucket, in the order given", () => {
    const rows = historyRows(BUCKETS);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.key)).toEqual(BUCKETS.map((b) => b.window_start));
  });

  it("never adds a row for the minutes between two buckets", () => {
    expect(historyRows(BUCKETS)).toHaveLength(BUCKETS.length);
  });

  it("names each bucket in UTC", () => {
    const [first, second] = historyRows(BUCKETS);
    expect(first.label).toBe("Sep 14 22:53");
    expect(second.label).toBe("Oct 6 02:26");
    expect(second.span).toBe("Oct 6, 02:26 UTC to Oct 6, 02:27 UTC");
  });

  it("keeps the success, blocked and error split and a missing latency as null", () => {
    const [, second] = historyRows(BUCKETS);
    expect([second.success, second.blocked, second.error]).toEqual([2, 1, 0]);
    expect(second.avgLatencyMs).toBeNull();
    expect(second.p95LatencyMs).toBeNull();
  });

  it("returns nothing for no buckets", () => {
    expect(historyRows([])).toEqual([]);
  });
});

describe("historyRequestTotal", () => {
  it("sums only the shown buckets", () => {
    expect(historyRequestTotal(historyRows(BUCKETS))).toBe(4);
    expect(historyRequestTotal([])).toBe(0);
  });
});
