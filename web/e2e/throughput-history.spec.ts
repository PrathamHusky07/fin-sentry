import { expect, test, type APIResponse } from "@playwright/test";

/**
 * The gateway's stored throughput-history route. Live Operations no longer draws these buckets
 * (the request history and its chart were removed from the page), but the gateway still serves
 * the route and the RisingWave view behind it still fills, so the route contract is checked
 * against the running stack. Needs the real stack.
 *
 * Status contract. 200 must carry a valid ThroughputHistory. 503 is the one honest unavailable
 * state (the gateway or its metrics service is down). Every other outcome is a failure: a 404
 * means the running gateway does not serve the route at all, which is a deployment or routing
 * fault and must never be accepted as "history unavailable".
 */
const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";
const ROUTE = `${GATEWAY}/ops/metrics/throughput/history?limit=60`;

interface Bucket {
  window_start: string;
  window_end: string;
  total_requests: number;
  success_count: number;
  blocked_count: number;
  error_count: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
}
interface History {
  generated_at: string;
  risingwave_connected: boolean;
  limit: number;
  window_start: string | null;
  window_end: string | null;
  buckets: Bucket[];
}

/** Read the route and enforce the status contract. Returns null on 503. */
async function readHistory(response: APIResponse): Promise<History | null> {
  const status = response.status();
  expect(
    [200, 503],
    `GET /ops/metrics/throughput/history returned ${status}; only 200 or 503 is a valid answer`,
  ).toContain(status);
  if (status === 503) return null;

  const body: unknown = await response.json();
  expect(typeof body, "history body is an object").toBe("object");
  const h = body as Record<string, unknown>;
  expect(typeof h.generated_at).toBe("string");
  expect(typeof h.risingwave_connected).toBe("boolean");
  expect(Number.isInteger(h.limit)).toBe(true);
  expect(Array.isArray(h.buckets)).toBe(true);
  const buckets = h.buckets as Record<string, unknown>[];
  for (const b of buckets) {
    expect(typeof b.window_start).toBe("string");
    expect(typeof b.window_end).toBe("string");
    for (const key of [
      "total_requests",
      "success_count",
      "blocked_count",
      "error_count",
    ]) {
      expect(Number.isInteger(b[key]), `${key} is an integer`).toBe(true);
      expect(b[key] as number).toBeGreaterThanOrEqual(0);
    }
    for (const key of ["avg_latency_ms", "p95_latency_ms"]) {
      expect(
        b[key] === null || typeof b[key] === "number",
        `${key} is a number or null`,
      ).toBe(true);
    }
  }
  const starts = buckets.map((b) => String(b.window_start));
  expect(starts, "buckets are oldest first").toEqual([...starts].sort());
  if (buckets.length === 0) {
    expect(h.window_start).toBeNull();
    expect(h.window_end).toBeNull();
  } else {
    expect(h.window_start).toBe(buckets[0].window_start);
    expect(h.window_end).toBe(buckets[buckets.length - 1].window_end);
  }
  return h as unknown as History;
}

test("the gateway serves the stored history route with the ThroughputHistory shape", async ({
  request,
}) => {
  await readHistory(await request.get(ROUTE));
});

test("every stored bucket reports one p95 over the same requests as its average", async ({
  request,
}) => {
  const body = await readHistory(
    await request.get(`${GATEWAY}/ops/metrics/throughput/history?limit=500`),
  );
  test.skip(body === null, "The metrics service answered 503, so no buckets.");
  const compared = (body as History).buckets.filter(
    (b) => b.p95_latency_ms !== null && b.avg_latency_ms !== null,
  );
  expect(compared.length).toBeGreaterThan(0);
  for (const b of compared) {
    // With at most 20 requests a continuous 95th percentile is never below the mean. A larger
    // bucket can legitimately sit under it when one value dominates, so it is not asserted.
    if (b.total_requests <= 20) {
      expect(b.p95_latency_ms as number).toBeGreaterThanOrEqual(
        b.avg_latency_ms as number,
      );
    }
  }
});

test("Live Operations no longer draws the stored buckets or any request-history section", async ({
  page,
}) => {
  await page.goto("/operations");
  await expect(
    page.getByRole("heading", { name: "Evaluation telemetry" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Stored request history" }),
  ).toHaveCount(0);
  await expect(
    page.locator("section[aria-labelledby='chart-heading']"),
  ).toHaveCount(0);
  await expect(page.locator("table")).toHaveCount(0);
});
