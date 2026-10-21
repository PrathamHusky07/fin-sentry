import { expect, test } from "@playwright/test";

/**
 * The Red Team console as an inspection surface. Reads the live registry and the stored
 * results. Nothing here starts a run: each test records every POST and asserts none was sent.
 */

const desktop = { width: 1440, height: 900 };

function posts(page: import("@playwright/test").Page): string[] {
  const sent: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") sent.push(r.url());
  });
  return sent;
}

test.describe("inspection first", () => {
  test.use({ viewport: desktop });

  test("on arrival the history and the execution workflow are collapsed and nothing is posted", async ({
    page,
  }) => {
    const sent = posts(page);
    await page.goto("/red-team");
    await expect(page.locator("[data-scenario]").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("#history-body")).toHaveCount(0);
    await expect(page.locator("#execute-body")).toHaveCount(0);
    await expect(page.locator('[aria-controls="history-body"]')).toContainText(
      /recorded executions?/,
    );
    // The first viewport holds the finding, not a log.
    await expect(page.locator("#attention")).toBeInViewport();
    await page.reload();
    expect(sent).toEqual([]);
  });

  test("four status filters with counts, kept in the URL, filter the list and the detail follows", async ({
    page,
  }) => {
    await page.goto("/red-team");
    const group = page.getByRole("group", { name: "Filter by status" });
    await expect(group.getByRole("button")).toHaveCount(4, {
      timeout: 15_000,
    });
    await expect(group.getByRole("button")).toHaveText([
      /^All\s*\d+$/,
      /^Completed\s*\d+$/,
      /^Failed\s*\d+$/,
      /^Interrupted\s*\d+$/,
    ]);
    await expect(page.locator("[data-scenario]")).toHaveCount(10);

    // Every stored execution finished with a verdict, so nothing is failed or interrupted.
    await group.getByRole("button", { name: /^Failed/ }).click();
    await expect(page).toHaveURL(/status=failed/);
    await expect(page.locator("[data-scenario]")).toHaveCount(0);
    await expect(
      page.getByText("No scenario matches these filters."),
    ).toBeVisible();
    await page.reload();
    await expect(
      group.getByRole("button", { name: /^Failed/ }),
    ).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });

    await group.getByRole("button", { name: /^Completed/ }).click();
    await expect(page.locator("[data-scenario]")).toHaveCount(10);
    await expect(page).toHaveURL(/status=completed/);
  });

  test("search narrows by id, title, defense or result and is kept in the URL", async ({
    page,
  }) => {
    await page.goto("/red-team");
    const search = page.getByRole("searchbox", { name: "Search scenarios" });
    await search.fill("pii", { timeout: 15_000 });
    await expect(page).toHaveURL(/q=pii/);
    await expect(page.locator("[data-scenario]")).not.toHaveCount(10);
    await expect(page.locator('[data-scenario="PII-001"]')).toBeVisible();
    await search.fill("missed");
    await expect(page.locator("[data-scenario]")).toHaveCount(1);
    await expect(page.locator('[data-scenario="GAP-001"]')).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).first().click();
    await expect(page.locator("[data-scenario]")).toHaveCount(10);
    await expect(page).not.toHaveURL(/q=/);
  });

  test("the panel on the right answers a selection: it follows the row and rebuilds in steps", async ({
    page,
  }) => {
    await page.goto("/red-team");
    const row = (id: string) =>
      page.locator(`[data-scenario="${id}"] .row-reveal`);
    await page
      .locator('[data-scenario="DI-001"] button[aria-expanded]')
      .click({ timeout: 15_000 });
    await expect(row("DI-001")).toHaveAttribute("data-active", "true");
    await expect(page.getByRole("article", { name: /DI-001/ })).toBeVisible();

    await page
      .locator('[data-scenario="HZ-001"] button[aria-expanded]')
      .click();
    await expect(row("HZ-001")).toHaveAttribute("data-active", "true");
    await expect(row("DI-001")).not.toHaveAttribute("data-active", "true");
    await expect(page.getByRole("article", { name: /DI-001/ })).toHaveCount(0);
    const article = page.getByRole("article", { name: /HZ-001/ });
    await expect(article).toBeVisible();
    // Expected and recorded sit side by side with the acting defense and its evidence.
    await expect(article).toContainText("Expected, stored with version 1");
    await expect(article).toContainText("Which defense acted");
    await expect(article).toContainText("Llama Guard 3");
    // The panel carries the row's tone, so it reads as belonging to the selection.
    const tone = await article
      .locator("xpath=..")
      .evaluate((el) => getComputedStyle(el).getPropertyValue("--tone").trim());
    expect(tone).toBe("#46d982");
  });

  test("the known gap card comes forward under the pointer", async ({
    page,
  }) => {
    await page.goto("/red-team");
    const card = page.locator('[data-attention="known_gap"]');
    await expect(card).toBeVisible({ timeout: 15_000 });
    const before = await card.boundingBox();
    const borderBefore = await card.evaluate(
      (el) => getComputedStyle(el).borderTopColor,
    );
    await card.hover();
    await expect
      .poll(async () => (await card.boundingBox())?.y ?? 0)
      .toBeLessThan(before?.y ?? 0);
    expect(
      await card.evaluate((el) => getComputedStyle(el).borderTopColor),
    ).not.toBe(borderBefore);
  });
});

test.describe("narrow", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("the filters stay usable and the workflow is reachable from the header", async ({
    page,
  }) => {
    const sent = posts(page);
    await page.goto("/red-team");
    const group = page.getByRole("group", { name: "Filter by status" });
    await expect(group.getByRole("button")).toHaveCount(4, {
      timeout: 15_000,
    });
    for (const b of await group.getByRole("button").all()) {
      expect((await b.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    await page.getByRole("button", { name: "Run scenarios" }).first().click();
    await expect(page.locator("#execute-body")).toBeVisible();
    expect(sent).toEqual([]);
  });
});
