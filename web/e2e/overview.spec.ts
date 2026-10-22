import { expect, test } from "@playwright/test";
import { DISAGREEMENT_IS_LIVE, NO_LIVE_DISAGREEMENT } from "./demo-record";

/**
 * /overview -- the command center. Real stack required. Checks the nav's
 * active-route state, the five sections in order, that no live telemetry
 * leaked in from Live Operations, and no console errors. Never a specific
 * numeric value: those are real and change as the corpus grows.
 */
test("Overview renders the command center sections with no console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/overview");

  await expect(
    page.getByRole("link", { name: "Overview", exact: true }).first(),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 }),
  ).toBeVisible();

  const state = page.getByRole("region", { name: "System state" });
  await expect(state.getByText("Frontier judge agreement")).toBeVisible();
  await expect(state.getByText("Delivered answers judged")).toBeVisible();

  for (const heading of [
    "Signals, most severe first",
    "Evaluation coverage",
    "Reliability pipeline",
  ]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
  // Recent investigations was cut from Overview: Signals, the featured
  // case and Investigations cover it.
  await expect(
    page.getByRole("heading", { name: "Recent investigations" }),
  ).toHaveCount(0);

  // A stored disagreement is featured with its real answer and scores. With none stored the
  // card is absent, never a placeholder.
  if (DISAGREEMENT_IS_LIVE) {
    const featured = page.getByRole("region", {
      name: /Amazon's FY2024 net income/,
    });
    await expect(featured).toContainText("1.000");
    await expect(featured).toContainText("0.000");
    await expect(featured).toContainText(/not readily available/);
  } else {
    await expect(page.locator("#featured-heading")).toHaveCount(0);
  }

  // Overview is not Live Operations: none of the live readouts belong here.
  await expect(page.getByText("Latency (avg / p95)")).toHaveCount(0);
  await expect(page.getByText("Judge tokens")).toHaveCount(0);
  await expect(page.getByText("Request activity")).toHaveCount(0);

  // Raw machine labels never appear in the user-facing funnel.
  await expect(page.getByText("malformed_json")).toHaveCount(0);
  await expect(page.getByText("input_rail_blocked")).toHaveCount(0);

  expect(errors).toEqual([]);
});

/**
 * The interaction layer on Overview. Values are real and change with the
 * corpus, so these assert behavior and structure, never a specific count.
 */
test.describe("Overview interactions", () => {
  test("the Amazon disagreement lights the hovered judge, dims the other and shows that judge's record", async ({
    page,
  }) => {
    test.skip(!DISAGREEMENT_IS_LIVE, NO_LIVE_DISAGREEMENT);
    await page.goto("/overview");
    const featured = page.getByRole("region", {
      name: /Amazon's FY2024 net income/,
    });
    const flash = featured.getByRole("button", {
      name: /Flash judge, faithfulness/,
    });
    const frontier = featured.getByRole("button", {
      name: /Frontier judge, faithfulness/,
    });
    await expect(flash).toContainText("1.000");
    await expect(frontier).toContainText("0.000");
    await expect(featured).toContainText(/apart/);
    await expect(featured).toContainText(/frontier judge’s reasoning/i);

    await flash.hover();
    await expect
      .poll(async () =>
        Number(await frontier.evaluate((el) => getComputedStyle(el).opacity)),
      )
      .toBeLessThan(0.5);
    await expect(featured).toContainText(/flash judge’s persisted record/i);
    await expect(featured).toContainText(/Answer relevance/);

    await frontier.hover();
    await expect
      .poll(async () =>
        Number(await flash.evaluate((el) => getComputedStyle(el).opacity)),
      )
      .toBeLessThan(0.5);
    await expect(
      featured.getByText(/explicitly contains Amazon/),
    ).toBeVisible();
  });

  test("a pipeline segment shows what it counts and opens its filtered executions", async ({
    page,
  }) => {
    await page.goto("/overview");
    const segment = page.getByRole("link", {
      name: /Delivered: \d+\. Open these executions/,
    });
    await segment.scrollIntoViewIfNeeded();
    await segment.hover();
    const tip = page
      .locator("#flow-heading")
      .locator("xpath=ancestor::section")
      .locator(".floating");
    await expect(tip).toContainText(/of \d+ requests/);
    await expect(tip).toContainText("Open these executions");
    await segment.click();
    await expect(page).toHaveURL(/\/investigations\?status=success/);
  });

  test("hovering a coverage group dims the others", async ({ page }) => {
    await page.goto("/overview");
    const groups = page
      .locator("#coverage-heading")
      .locator("xpath=ancestor::section")
      .getByRole("link");
    const first = groups.first();
    const last = groups.last();
    await first.scrollIntoViewIfNeeded();
    await first.hover();
    await expect
      .poll(async () =>
        Number(await last.evaluate((el) => getComputedStyle(el).opacity)),
      )
      .toBeLessThan(0.5);
  });

  test("the system state shows the figure and a compact calibration card that links to the full instrument", async ({
    page,
  }) => {
    await page.goto("/overview");
    const state = page.getByRole("region", { name: "System state" });
    const card = state.getByRole("link", { name: /Frontier judge agreement/ });
    await expect(card).toHaveAttribute("href", "/operations#calibration");
    await expect(card).toContainText("Open the full instrument");
    await expect(
      page.getByRole("heading", { name: "Recent investigations" }),
    ).toHaveCount(0);
  });
});
