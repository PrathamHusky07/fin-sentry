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

  const telemetry = page.getByRole("region", { name: "Request activity" });
  for (const label of [
    "Throughput",
    "Average RAG latency",
    "p95 RAG latency",
  ]) {
    await expect(telemetry.getByText(label, { exact: true })).toBeVisible();
  }
  for (const label of ["Judge tokens", "Judge cost"]) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
  // Token and cost scope is the flash judge, never "platform" totals.
  await expect(page.getByText(/Flash judge only/).first()).toBeVisible();

  // The chart heading follows the stored data: the last hour while buckets are fresh, and
  // the last recorded activity once the newest stored bucket is stale (live-ops-stale.spec.ts).
  await expect(
    page.getByRole("heading", {
      name: /^(Request buckets, last hour|Last recorded activity)$/,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Calibration" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Evaluation telemetry" }),
  ).toBeVisible();
  // The recent-events list was cut: Investigations and Overview cover it.
  await expect(
    page.getByRole("heading", { name: "Recent operational events" }),
  ).toHaveCount(0);
});
