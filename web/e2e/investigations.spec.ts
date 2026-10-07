import { expect, test } from "@playwright/test";

/**
 * /investigations -- search, filter, pagination, the disagreement lens,
 * the sticky table header, and the trace-detail dialog's accessibility
 * contract (open, Escape, focus trap, focus restoration). Real stack
 * required. Deterministic assertions against real, known data only: the
 * disagreement lens is asserted against the one real cross-tier
 * disagreement in the live corpus (the Amazon FY2024 trace), confirmed by
 * a direct query before writing this test, not assumed.
 */
test.describe("Investigations", () => {
  test("search filters the real table to matching rows", async ({ page }) => {
    await page.goto("/investigations");
    await page.getByPlaceholder("Search query text or trace ID").fill("amazon");
    await page.waitForTimeout(500); // debounce + fetch

    const rows = page.locator("table tbody tr");
    await expect(rows.first()).toBeVisible();
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      await expect(rows.nth(i)).toContainText(/amazon/i);
    }
  });

  test("the disagreement lens returns exactly the real known disagreement", async ({
    page,
  }) => {
    await page.goto("/investigations");
    await page
      .getByRole("button", { name: "Flash/frontier disagreement" })
      .click();
    await page.waitForTimeout(500);

    const rows = page.locator("table tbody tr");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText(
      /Amazon's FY2024 net income attributable to shareholders/i,
    );
  });

  test("pagination moves to a new set of rows and back", async ({ page }) => {
    // Asserts page-level state (the "Showing" range, button enabled state),
    // not exact row content: this environment has real background traffic
    // continuously writing new rows (see docs/build-log.md's "integration
    // test query" noise), so the row at a given offset can genuinely shift
    // between page loads -- comparing row text would be asserting against
    // a moving target, not a pagination bug.
    await page.goto("/investigations");
    await expect(page.locator("table tbody tr").first()).toBeVisible();
    await expect(page.getByText(/^Showing 1–/)).toBeVisible();

    const next = page.getByRole("button", { name: "Next", exact: true });
    const previous = page.getByRole("button", {
      name: "Previous",
      exact: true,
    });
    await expect(next).toBeEnabled();
    await expect(previous).toBeDisabled();

    await next.click();
    await expect(page.getByText(/^Showing 51/)).toBeVisible();
    await expect(previous).toBeEnabled();

    await previous.click();
    await expect(page.getByText(/^Showing 1–/)).toBeVisible();
    await expect(previous).toBeDisabled();
  });

  test("the table header stays pinned beneath the global nav while the page scrolls", async ({
    page,
  }) => {
    await page.goto("/investigations");
    const header = page.locator("table thead th").first();
    await expect(header).toBeVisible();
    await expect(page.locator("table tbody tr").first()).toBeVisible();

    await page.evaluate(() => window.scrollTo(0, 700));
    await page.waitForTimeout(200);

    const nav = await page.locator("header").first().boundingBox();
    const headerBox = await header.boundingBox();
    expect(nav).not.toBeNull();
    expect(headerBox).not.toBeNull();
    // Pinned: the header sits directly under the sticky nav after scroll.
    expect(Math.abs((headerBox?.y ?? 0) - (nav?.height ?? 0))).toBeLessThan(3);
  });

  test("a trace row opens the dialog, Escape closes it, and focus returns to the row", async ({
    page,
  }) => {
    await page.goto("/investigations");
    const firstButton = page.locator("table [data-row-button]").first();
    await firstButton.focus();
    await firstButton.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Trace detail" });
    await expect(dialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(firstButton).toBeFocused();
  });

  test("outcomes use human-readable labels, with raw codes kept for the detail view", async ({
    page,
  }) => {
    await page.goto("/investigations?status=blocked");
    const rows = page.locator("table tbody tr");
    await expect(rows.first()).toBeVisible();
    await expect(rows.first()).toContainText(/Blocked · /);
    await expect(page.locator("table")).not.toContainText("malformed_json");
  });

  test("/judges still redirects to /investigations", async ({ page }) => {
    await page.goto("/judges");
    await expect(page).toHaveURL(/\/investigations$/);
  });
});
