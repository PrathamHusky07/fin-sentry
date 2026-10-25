import { describe, expect, it } from "vitest";
import { latestFrom } from "@/lib/archive/probe";
import { serveArchive } from "@/lib/archive/serve";

// The expected figures were read from the gateway_probe_runs row with psql on 2026-10-25, not
// from the code under test. The run itself was recorded on 2026-10-22.
const RECORDED = {
  measured_at: "2026-10-22T22:28:42.250590Z",
  target: "http://localhost:8000/health",
  samples: 30,
  median_ms: 0.26016650372184813,
  p95_ms: 0.35385015944484616,
  max_ms: 0.38283399771898985,
};

const row = (id: number, measuredAt: string, median: number) => ({
  id,
  measured_at: measuredAt,
  target: "http://localhost:8000/health",
  samples: 30,
  median_ms: median,
  p95_ms: median * 2,
  max_ms: median * 3,
});

describe("the archived gateway probe", () => {
  it("is served at the gateway's own path with the recorded figures and their original time", async () => {
    const res = await serveArchive("/ops/gateway-probe/latest");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      latest: Record<string, unknown>;
      runs_recorded: number;
    };
    expect(body).toEqual({ latest: RECORDED, runs_recorded: 1 });
    // The live route's field names and order, so the frontend needs no shape change.
    expect(Object.keys(body.latest)).toEqual([
      "measured_at",
      "target",
      "samples",
      "median_ms",
      "p95_ms",
      "max_ms",
    ]);
    // The recording time is the stored one, never the time of the read.
    expect(Date.parse(body.latest.measured_at as string)).toBeLessThan(
      Date.parse("2026-10-23T00:00:00Z"),
    );
  });
});

describe("latestFrom", () => {
  it("takes the newest recording time whatever the row order, and counts every row", () => {
    const summary = latestFrom([
      row(2, "2026-10-22T22:28:42.25059+00:00", 0.26),
      row(3, "2026-10-24T08:00:00+00:00", 0.31),
      row(1, "2026-10-20T10:00:00+00:00", 0.4),
    ]);
    expect(summary.runs_recorded).toBe(3);
    expect(summary.latest).toEqual({
      measured_at: "2026-10-24T08:00:00Z",
      target: "http://localhost:8000/health",
      samples: 30,
      median_ms: 0.31,
      p95_ms: 0.62,
      max_ms: 0.31 * 3,
    });
  });

  it("breaks a tie on the recording time with the higher id", () => {
    const summary = latestFrom([
      row(1, "2026-10-22T22:28:42+00:00", 0.2),
      row(2, "2026-10-22T22:28:42+00:00", 0.3),
    ]);
    expect(summary.latest?.median_ms).toBe(0.3);
  });

  it("says no run was recorded and does not invent one", () => {
    expect(latestFrom([])).toEqual({ latest: null, runs_recorded: 0 });
  });
});
