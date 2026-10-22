import { expect, test } from "@playwright/test";

/**
 * Live Operations shows two different latencies and must never let one pass for the other. The
 * metrics buckets time whole RAG queries. The gateway health check times one cheap route that
 * runs no retrieval and no model. Needs the gateway, because the web server times it.
 */
test.use({ viewport: { width: 1440, height: 900 } });

test("the gateway health check is measured, separate and labeled as not request latency", async ({
  page,
}) => {
  const issues: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(m.text());
  });
  await page.goto("/operations");

  const check = page.locator("[data-gateway-health]");
  await expect(check).toHaveAttribute("data-gateway-health", "measured");
  await expect(check).toContainText("Gateway health check");
  await expect(check).toContainText("runs no retrieval and no model");
  await expect(check).toContainText("not request latency");
  const ms = Number(
    (await check.innerText()).match(/Gateway health check\s*([\d.]+) ms/)?.[1],
  );
  expect(ms).toBeGreaterThan(0);
  expect(ms).toBeLessThan(1000);

  // The bucket readouts say they time RAG queries, so they cannot be read as this number.
  const readouts = page.locator("#activity-heading + dl");
  await expect(readouts).toContainText("RAG queries recorded");
  await expect(readouts).toContainText("retrieval and generation included");
  await expect(readouts).not.toContainText("Gateway requests");
  await expect(readouts).not.toContainText("Gateway health check");
  expect(issues).toEqual([]);
});
