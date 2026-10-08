import { describe, expect, it } from "vitest";
import type { ThroughputBucket } from "@/lib/metrics-snapshot";
import {
  ACTIVITY_WINDOW_MS,
  historyRequestTotal,
  historyRows,
  mergeActivityBuckets,
} from "@/lib/throughput-history";

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

function stored(endIso: string, total: number): ThroughputBucket {
  const end = new Date(endIso).getTime();
  return {
    window_start: new Date(end - 60_000).toISOString(),
    window_end: endIso,
    total_requests: total,
    success_count: total,
    blocked_count: 0,
    error_count: 0,
    avg_latency_ms: 100,
    p95_latency_ms: 120,
  };
}

function received(endIso: string, total: number) {
  return {
    windowEnd: endIso,
    totalRequests: total,
    avgLatencyMs: 90,
    p95LatencyMs: 110,
  };
}

describe("mergeActivityBuckets", () => {
  it("puts stored buckets first and received buckets after, oldest first", () => {
    const merged = mergeActivityBuckets(
      [stored("2026-10-08T19:31:00Z", 2), stored("2026-10-08T19:32:00Z", 4)],
      [received("2026-10-08T19:34:00Z", 3)],
      false,
    );
    expect(merged.map((b) => b.windowEnd)).toEqual([
      "2026-10-08T19:31:00Z",
      "2026-10-08T19:32:00Z",
      "2026-10-08T19:34:00Z",
    ]);
  });

  it("counts a bucket present in both sources once, and the received values win", () => {
    const merged = mergeActivityBuckets(
      [stored("2026-10-08T19:33:00Z", 2)],
      // Same instant, written with milliseconds: still one bucket.
      [received("2026-10-08T19:33:00.000Z", 5)],
      false,
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].totalRequests).toBe(5);
    expect(merged[0].avgLatencyMs).toBe(90);
  });

  it("leaves a gap as a gap: no bucket is invented for a missing minute", () => {
    const merged = mergeActivityBuckets(
      [stored("2026-10-08T19:30:00Z", 1), stored("2026-10-08T19:34:00Z", 1)],
      [],
      false,
    );
    expect(merged).toHaveLength(2);
  });

  it("flags only the newest received bucket as live, and only when the edge is live", () => {
    const stream = [received("2026-10-08T19:33:00Z", 2)];
    const history = [stored("2026-10-08T19:32:00Z", 1)];
    const live = mergeActivityBuckets(history, stream, true);
    expect(live.map((b) => b.source)).toEqual(["stored", "live"]);
    const notLive = mergeActivityBuckets(history, stream, false);
    expect(notLive.map((b) => b.source)).toEqual(["stored", "stored"]);
  });

  it("never calls a bucket known only from storage live, even when the edge is live", () => {
    const merged = mergeActivityBuckets(
      [stored("2026-10-08T19:35:00Z", 7)],
      [received("2026-10-08T19:34:00Z", 3)],
      true,
    );
    expect(merged.map((b) => b.source)).toEqual(["stored", "stored"]);
  });

  it("keeps only the window ending at the newest bucket", () => {
    const merged = mergeActivityBuckets(
      [
        stored("2026-10-04T19:18:00Z", 1),
        stored("2026-10-08T18:34:00Z", 1),
        stored("2026-10-08T18:33:59Z", 1),
        stored("2026-10-08T19:34:00Z", 1),
      ],
      [],
      false,
    );
    expect(merged.map((b) => b.windowEnd)).toEqual([
      "2026-10-08T18:34:00Z",
      "2026-10-08T19:34:00Z",
    ]);
    expect(ACTIVITY_WINDOW_MS).toBe(3_600_000);
  });

  it("with no stored history it is exactly the received buckets, as before", () => {
    const stream = [
      received("2026-10-08T19:31:00Z", 1),
      received("2026-10-08T19:32:00Z", 2),
    ];
    const merged = mergeActivityBuckets([], stream, false);
    expect(merged.map((b) => b.totalRequests)).toEqual([1, 2]);
  });

  it("returns nothing when neither source has a bucket", () => {
    expect(mergeActivityBuckets([], [], true)).toEqual([]);
  });
});
