import { expect, test } from "@playwright/test";

/**
 * Proves a real MetricsSnapshot crosses the wire: browser -> EventSource ->
 * gateway /ops/stream -> MetricsPoller -> dashboard /metrics/snapshot ->
 * RisingWave. Requires the real stack running (see playwright.config.ts).
 */
test("the Live Operations page receives and renders a real snapshot over SSE", async ({
  page,
}) => {
  await page.goto("/operations");

  await expect(page.getByText("SSE connectivity proof")).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({ timeout: 10_000 });

  // Wait for the probe to replace its "waiting" placeholder with a real
  // rendered snapshot -- not a fixed sleep.
  await expect(page.getByText("Waiting for the first snapshot")).not.toBeVisible({
    timeout: 10_000,
  });

  const fields = page.locator("dl");
  await expect(fields).toContainText("generated_at");
  await expect(fields).toContainText("risingwave_connected");
});
