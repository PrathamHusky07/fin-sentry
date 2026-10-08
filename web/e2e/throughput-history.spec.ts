import { expect, test, type APIResponse } from "@playwright/test";

/**
 * The stored request history on Live Operations. The page reads
 * GET /ops/metrics/throughput/history on the gateway, so these tests read the
 * same route and hold the page to it. Needs the real stack.
 *
 * Status contract. 200 must carry a valid ThroughputHistory. 503 is the one
 * honest unavailable state (the gateway or its metrics service is down) and
 * the page must say so. Every other outcome is a failure: a 404 means the
 * running gateway does not serve the route at all, which is a deployment or
 * routing fault and must never be accepted as "history unavailable".
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

test("Live Operations draws the stored buckets the gateway returns, or says it has none", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  const first = await readHistory(await request.get(ROUTE));
  await page.goto("/operations");
  const second = await readHistory(await request.get(ROUTE));

  const section = page.getByRole("region", { name: "Stored request history" });
  await expect(section).toBeVisible();
  // Stored history says where it came from and is never described as arriving
  // over the stream.
  await expect(section).toContainText("persisted by the metrics view");
  await expect(section).not.toContainText("arrived over the stream");

  if (first === null || second === null) {
    await expect(section).toContainText("Stored history is not available");
    await expect(section.locator("table")).toHaveCount(0);
    expect(errors).toEqual([]);
    return;
  }

  if (!first.risingwave_connected || !second.risingwave_connected) {
    await expect(section).toContainText("metrics store is offline");
    expect(errors).toEqual([]);
    return;
  }

  const counts = new Set([first.buckets.length, second.buckets.length]);
  if (counts.has(0)) {
    await expect(section).toContainText(
      "No one-minute bucket has been stored yet",
    );
    expect(errors).toEqual([]);
    return;
  }

  await section.getByText("View the stored buckets as a table").click();
  const rows = await section.locator("tbody tr").count();
  expect([...counts]).toContain(rows);
  await expect(section).toContainText(
    `${rows} stored ${rows === 1 ? "bucket" : "buckets"} covering`,
  );
  await expect(section).toContainText("Nothing is filled in between them");
  expect(errors).toEqual([]);
});
