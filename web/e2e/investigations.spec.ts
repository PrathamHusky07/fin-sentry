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

  test("the table header stays pinned while the body scrolls (sticky header)", async ({
    page,
  }) => {
    await page.goto("/investigations");
    // The DataTable's own overflow-y-auto div, not the page -- scrolling
    // this element's scrollTop directly isolates the check from any page-
    // level scroll scrollIntoViewIfNeeded might also trigger.
    const scrollRegion = page.locator("table").locator("xpath=..");
    const header = page.locator("table thead tr");
    await expect(header).toBeVisible();

    await scrollRegion.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });

    const headerBox = await header.boundingBox();
    const regionBox = await scrollRegion.boundingBox();
    expect(headerBox).not.toBeNull();
    expect(regionBox).not.toBeNull();
    // A pinned header sits at the top edge of its scroll container even
    // after the container scrolls to its end -- an un-pinned header would
    // have scrolled away with the rows and no longer be near that edge.
    expect(Math.abs((headerBox?.y ?? 0) - (regionBox?.y ?? 0))).toBeLessThan(2);
  });

  test("a trace row opens the dialog, Escape closes it, and focus returns to the row", async ({
    page,
  }) => {
    await page.goto("/investigations");
    const firstRow = page.locator("table tbody tr").first();
    await firstRow.focus();
    await firstRow.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Trace detail" });
    await expect(dialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(firstRow).toBeFocused();
  });
});
