import { expect, test } from "@playwright/test";

/**
 * /architecture, /red-team and the sticky global shell. Static content,
 * so these assert structure and the corrected claims, not live numbers.
 */
test("Architecture lays out four layers and keeps its claims source-accurate", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/architecture");
  await expect(
    page.getByRole("heading", { name: /How Fin-Sentry is built/, level: 1 }),
  ).toBeVisible();
  for (const layer of [
    "Request path",
    "Evaluation plane",
    "Event infrastructure",
    "Operational interface",
  ]) {
    await expect(
      page.getByRole("heading", { name: layer, level: 2 }),
    ).toBeVisible();
  }

  const body = page.locator("body");
  await expect(body).toContainText("gemini-3.6-flash");
  await expect(body).not.toContainText(/2\.5 Flash/);
  await expect(body).not.toContainText(/weekly/i);
  await expect(body).toContainText("not a live monitor");
  // No repo paths or dev hosts on the page.
  await expect(body).not.toContainText(
    /finsentry\/|Read from|docs\/adr|\.py\b/,
  );
  await expect(body).not.toContainText(/localhost|127\.0\.0\.1|:3000|:8000/);
  // Four distinct diagrams: a pipeline, a topology, event lanes and a hub.
  await expect(
    page.getByRole("list", { name: "The request path, left to right" }),
  ).toBeVisible();
  for (const name of [
    /evaluation plane\. A response event forks/i,
    /two lanes around a log/i,
    /operational interface as a hub/i,
  ]) {
    await expect(page.getByRole("img", { name })).toBeVisible();
  }
  // Red Team is shown as not built, never as a working capability.
  await expect(body).toContainText("not registered");

  expect(errors).toEqual([]);
});

test("Red Team states it is not built", async ({ page }) => {
  await page.goto("/red-team");
  await expect(
    page.getByRole("heading", { name: "Red Team", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Not built", { exact: true })).toBeVisible();
});

test("the global navigation stays pinned while scrolling", async ({ page }) => {
  await page.goto("/architecture");
  await page.evaluate(() => window.scrollTo(0, 1800));
  await page.waitForTimeout(200);
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toBeVisible();
  const box = await nav.boundingBox();
  expect(Math.abs(box?.y ?? 99)).toBeLessThan(2);
  for (const name of [
    "Overview",
    "Live Operations",
    "Investigations",
    "Architecture",
    "Red Team",
  ]) {
    await expect(nav.getByRole("link", { name })).toBeVisible();
  }
});
