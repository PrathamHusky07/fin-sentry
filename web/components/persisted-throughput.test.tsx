import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PersistedThroughput } from "@/components/persisted-throughput";
import type { ThroughputHistory } from "@/lib/metrics-snapshot";

const BASE: ThroughputHistory = {
  generated_at: "2026-10-08T00:30:00Z",
  risingwave_connected: true,
  limit: 60,
  window_start: "2026-10-06T02:25:00Z",
  window_end: "2026-10-06T02:27:00Z",
  buckets: [
    {
      window_start: "2026-10-06T02:25:00Z",
      window_end: "2026-10-06T02:26:00Z",
      total_requests: 1,
      success_count: 1,
      blocked_count: 0,
      error_count: 0,
      avg_latency_ms: 100,
      p95_latency_ms: 100.5,
    },
    {
      window_start: "2026-10-06T02:26:00Z",
      window_end: "2026-10-06T02:27:00Z",
      total_requests: 3,
      success_count: 3,
      blocked_count: 0,
      error_count: 0,
      avg_latency_ms: 100,
      p95_latency_ms: 100.5,
    },
  ],
};

function html(history: ThroughputHistory | null): string {
  return renderToStaticMarkup(<PersistedThroughput history={history} />);
}

describe("PersistedThroughput", () => {
  it("says history is unavailable instead of drawing an empty chart", () => {
    const out = html(null);
    expect(out).toContain("Stored history is not available");
    expect(out).not.toContain("<table");
  });

  it("says the store is offline, and that offline is not a quiet system", () => {
    const out = html({ ...BASE, risingwave_connected: false, buckets: [] });
    expect(out).toContain("metrics store is offline");
    expect(out).toContain("not a quiet system");
  });

  it("says no bucket is stored when there are none", () => {
    const out = html({
      ...BASE,
      window_start: null,
      window_end: null,
      buckets: [],
    });
    expect(out).toContain("No one-minute bucket has been stored yet");
  });

  it("draws the stored buckets with their provenance and no fill-in", () => {
    const out = html(BASE);
    expect(out).toContain("Read Oct 8, 00:30 UTC when this page loaded");
    expect(out).toContain("2 stored buckets covering 4 requests");
    expect(out).toContain("Nothing is filled in between them");
    // One table row per stored bucket plus the header row.
    expect(out.match(/<tr/g)).toHaveLength(3);
  });
});
