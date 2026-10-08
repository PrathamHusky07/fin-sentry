import { expect, test } from "@playwright/test";

/**
 * The stored request history on Live Operations. The page reads
 * GET /ops/metrics/throughput/history on the gateway, so this test reads the
 * same route and holds the page to it: one table row per stored bucket, the
 * counts the route returned, and an explicit unavailable state when the
 * gateway cannot return history. Needs the real stack.
 */
const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";
const ROUTE = `${GATEWAY}/ops/metrics/throughput/history?limit=60`;

interface Bucket {
  total_requests: number;
}
interface History {
  risingwave_connected: boolean;
  buckets: Bucket[];
}

test("Live Operations draws the stored buckets the gateway returns, or says it has none", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  const before = await request.get(ROUTE);
  await page.goto("/operations");
  const after = await request.get(ROUTE);

  const section = page.getByRole("region", { name: "Stored request history" });
  await expect(section).toBeVisible();
  // Stored history says where it came from and is never described as arriving
  // over the stream.
  await expect(section).toContainText("persisted by the metrics view");
  await expect(section).not.toContainText("arrived over the stream");

  if (!before.ok() || !after.ok()) {
    await expect(section).toContainText("Stored history is not available");
    await expect(section.locator("table")).toHaveCount(0);
    expect(errors).toEqual([]);
    return;
  }

  const first = (await before.json()) as History;
  const second = (await after.json()) as History;
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
