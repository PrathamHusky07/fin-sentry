import { expect, test } from "@playwright/test";

/**
 * Proves a real MetricsSnapshot crosses the wire: browser -> EventSource ->
 * gateway /ops/stream -> MetricsPoller -> dashboard /metrics/snapshot ->
 * RisingWave, and that the real Live Operations UI renders it -- not the
 * Day 8 raw <dl> connectivity probe this test used to check for. Requires
 * the real stack running (see playwright.config.ts).
 */
test("the Live Operations page receives and renders a real snapshot over SSE", async ({
  page,
}) => {
  await page.goto("/operations");

  await expect(page.getByText("System health")).toBeVisible();
  await expect(page.getByText("SSE connected")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("RisingWave connected")).toBeVisible({
    timeout: 10_000,
  });

  // The four real metric tiles, sourced from the live MetricsSnapshot.
  await expect(page.getByText("Throughput")).toBeVisible();
  await expect(page.getByText("Latency (avg / p95)")).toBeVisible();
  await expect(page.getByText("Token usage")).toBeVisible();
  await expect(page.getByText("Cost")).toBeVisible();
});
