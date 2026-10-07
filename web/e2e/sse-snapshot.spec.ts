import { expect, test } from "@playwright/test";

/**
 * Proves a real MetricsSnapshot crosses the wire: browser -> EventSource ->
 * gateway /ops/stream -> MetricsPoller -> dashboard /metrics/snapshot ->
 * RisingWave, and that Live Operations renders it with its scope labels.
 * Requires the real stack running (see playwright.config.ts).
 */
test("Live Operations receives a real snapshot over SSE and labels every readout", async ({
  page,
}) => {
  await page.goto("/operations");

  await expect(page.getByText("Connected", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Reachable", { exact: true })).toBeVisible({
    timeout: 10_000,
  });

  const readouts = page.getByRole("region", { name: "Readouts" });
  for (const label of [
    "Throughput",
    "Average latency",
    "p95 latency",
    "Judge tokens",
    "Judge cost",
  ]) {
    await expect(readouts.getByText(label, { exact: true })).toBeVisible();
  }
  // Token and cost scope is the flash judge, never "platform" totals.
  await expect(readouts.getByText(/Flash judge only/).first()).toBeVisible();

  await expect(
    page.getByRole("heading", { name: "Request activity" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Calibration" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent operational events" }),
  ).toBeVisible();
});
