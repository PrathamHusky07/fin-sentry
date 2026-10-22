import { describe, expect, it } from "vitest";
import { measureGatewayHealth, median } from "@/lib/gateway-health";

/** A clock that advances by the next listed duration on every second reading. */
function clockFor(durations: number[]): () => number {
  let now = 0;
  let reads = 0;
  return () => {
    const read = now;
    if (reads % 2 === 0) now += durations[reads / 2] ?? 0;
    reads += 1;
    return read;
  };
}

const ok = () => Promise.resolve(new Response("{}", { status: 200 }));

describe("median", () => {
  it("takes the middle of an odd list and the mean of the middle two of an even one", () => {
    expect(median([9, 1, 5])).toBe(5);
    expect(median([4, 2, 8, 6])).toBe(5);
  });
});

describe("measureGatewayHealth", () => {
  it("reports the median of the timed requests, not the mean", async () => {
    const result = await measureGatewayHealth({
      fetchFn: ok,
      clock: clockFor([4, 100, 6]),
    });
    expect(result?.medianMs).toBe(6);
    expect(result?.samples).toBe(3);
    expect(Number.isNaN(Date.parse(result?.measuredAt ?? ""))).toBe(false);
  });

  it("is null when the gateway answers with an error status", async () => {
    const result = await measureGatewayHealth({
      fetchFn: () => Promise.resolve(new Response("no", { status: 503 })),
    });
    expect(result).toBeNull();
  });

  it("is null when the gateway cannot be reached, never a fast number", async () => {
    const result = await measureGatewayHealth({
      fetchFn: () => Promise.reject(new TypeError("fetch failed")),
    });
    expect(result).toBeNull();
  });
});
