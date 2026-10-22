import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchGatewayProbe, formatMs } from "@/lib/gateway-probe";

afterEach(() => vi.unstubAllGlobals());

describe("formatMs", () => {
  it("keeps precision where the figure is small", () => {
    expect(formatMs(0.26016)).toBe("0.26");
    expect(formatMs(9.994)).toBe("9.99");
    expect(formatMs(42.46)).toBe("42.5");
    expect(formatMs(1234.5)).toBe("1235");
  });
});

describe("fetchGatewayProbe", () => {
  it("returns the stored summary as served", async () => {
    const body = {
      latest: {
        measured_at: "2026-10-22T22:28:42Z",
        target: "http://localhost:8000/health",
        samples: 30,
        median_ms: 0.26,
        p95_ms: 0.35,
        max_ms: 0.38,
      },
      runs_recorded: 1,
    };
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response(JSON.stringify(body), { status: 200 })),
    );
    expect(await fetchGatewayProbe()).toEqual(body);
  });

  it("is null, not an empty summary, when the store answers with an error", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response("{}", { status: 503 })),
    );
    expect(await fetchGatewayProbe()).toBeNull();
  });

  it("is null when the gateway cannot be reached", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("fetch failed")));
    expect(await fetchGatewayProbe()).toBeNull();
  });
});
