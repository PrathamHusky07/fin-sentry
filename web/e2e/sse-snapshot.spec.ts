import { expect, test } from "@playwright/test";

/**
 * Proves a real MetricsSnapshot crosses the wire: browser -> EventSource ->
 * gateway /ops/stream -> MetricsPoller -> dashboard /metrics/snapshot ->
 * RisingWave, and that the Evaluation telemetry cards on Live Operations render it with
 * their window labels. The old connection pills and request-activity readouts are gone, so
 * the proof is the stream response itself plus the cards that only a snapshot can fill.
 * Requires the real stack running (see playwright.config.ts).
 */
test("Live Operations receives a real snapshot over SSE and labels every evaluation readout", async ({
  page,
}) => {
  const stream = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/ops/stream",
    { timeout: 15_000 },
  );
  await page.goto("/operations");

  const response = await stream;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("text/event-stream");

  const telemetry = page.locator("section[aria-labelledby='eval-heading']");
  await expect(
    telemetry.getByRole("heading", { name: "Evaluation telemetry" }),
  ).toBeVisible();

  // Four cards, each naming its window. "Latest one-minute bucket, ended ..." comes from
  // the snapshot and nowhere else.
  const cards = telemetry.locator("section[data-stale]");
  await expect(cards).toHaveCount(4);
  await expect(
    telemetry.getByText(/Latest one-minute bucket, ended .* UTC/).first(),
  ).toBeVisible({ timeout: 10_000 });
  // The frontier card sums a 15 minute window, so it reports either its newest bucket or that
  // none is in range. Both are honest answers and which one holds depends on recent traffic.
  await expect(
    telemetry.getByText(
      /Summed over the window, (newest bucket ended .* UTC|no bucket in range)/,
    ),
  ).toBeVisible();
  for (const title of [
    "Flash judge, faithfulness",
    "Flash judge, relevance",
    "Judge usage",
    /^Frontier tier, last \d+ minutes$/,
  ]) {
    await expect(telemetry.getByRole("heading", { name: title })).toBeVisible();
  }

  // The flash cards hold stored values, not placeholders.
  const faithfulness = telemetry.locator(
    "section[aria-label='Flash judge, faithfulness']",
  );
  await expect(faithfulness.getByText("no data")).toHaveCount(0);
  await expect(faithfulness.getByText("Average faithfulness")).toBeVisible();

  for (const label of ["Judge tokens", "Judge cost"]) {
    await expect(telemetry.getByText(label, { exact: true })).toBeVisible();
  }
  // Token and cost scope is the flash judge, never "platform" totals.
  await expect(telemetry.getByText(/Flash judge only/).first()).toBeVisible();
  await expect(telemetry.getByText(/Not platform spend/)).toBeVisible();

  // A reachable stream never shows the unavailable state.
  await expect(
    page.getByText("Evaluation telemetry is unavailable"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Calibration" }),
  ).toBeVisible();
  // The recent-events list was cut: Investigations and Overview cover it.
  await expect(
    page.getByRole("heading", { name: "Recent operational events" }),
  ).toHaveCount(0);
});
