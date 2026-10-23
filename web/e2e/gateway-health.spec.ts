import { expect, test } from "@playwright/test";

/**
 * The gateway reading on Live Operations. The recorded probe is a stored reading of the gateway
 * health route and leads the card. The page's own check times the same route once per visit,
 * stores nothing and stays visibly the smaller, momentary figure. The scope is named once as
 * the gateway health route, and neither figure is presented as anything wider. Needs the
 * gateway, because it serves the probe.
 */
test.use({ viewport: { width: 1440, height: 900 } });

test("the recorded gateway probe leads the card, is dated and names the gateway health route once", async ({
  page,
}) => {
  const issues: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(m.text());
  });
  await page.goto("/operations");

  const probe = page.locator("[data-gateway-probe]");
  await expect(probe).toHaveAttribute("data-gateway-probe", "recorded");
  await expect(probe).toContainText("Health-route round trip, recorded probe");
  await expect(page.locator("#gateway")).toContainText(
    "gateway answers on its health route",
  );
  const text = await probe.innerText();
  expect(text).toMatch(/Recorded \w{3} \d+, \d{2}:\d{2} UTC/);
  const median = Number(text.match(/([\d.]+)\s*ms median/)?.[1]);
  expect(median).toBeGreaterThan(0);
  expect(median).toBeLessThan(1000);
  expect(text).toMatch(/p95 [\d.]+ ms/);
  expect(text).toMatch(/max [\d.]+ ms/);
  expect(text).toMatch(/\d+ requests/);
  // The timing method is one quiet line, not a disclaimer repeated down the card.
  await expect(probe).toContainText("after two warm-up requests");
  expect(text.match(/retrieval/gi) ?? []).toHaveLength(0);

  // The figure comes before its caption, and the card never mentions RAG.
  const figure = await probe.locator("p.text-4xl").boundingBox();
  const caption = await probe.getByText(/^Recorded /).boundingBox();
  expect(figure && caption && figure.y < caption.y).toBe(true);
  await expect(page.locator("#gateway")).not.toContainText(/RAG/);
  expect(issues).toEqual([]);
});

test("the page's own health check is bounded, separate, smaller and not stored", async ({
  page,
}) => {
  await page.goto("/operations");

  const check = page.locator("[data-gateway-health]");
  await expect(check).toHaveAttribute("data-gateway-health", "measured");
  await expect(check).toContainText("Checked just now by this page");
  await expect(check).toContainText("and not stored");
  await expect(check).toContainText("gateway health route");
  const ms = Number(
    (await check.innerText()).match(/this page\s*([\d.]+) ms/)?.[1],
  );
  expect(ms).toBeGreaterThan(0);
  expect(ms).toBeLessThan(1500);

  // It is the momentary reading: a smaller figure than the recorded one, in its own row.
  const size = (selector: string) =>
    page
      .locator(selector)
      .first()
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  const recorded = await size("[data-gateway-probe] p.text-4xl");
  const momentary = await size("[data-gateway-health] span.tabular-metric");
  expect(momentary).toBeLessThan(recorded);
});
