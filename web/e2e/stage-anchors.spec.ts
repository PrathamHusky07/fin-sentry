import { expect, test } from "@playwright/test";

/**
 * The landing stage cards each open a different part of the product, and the
 * architecture page still marks a stage when its anchor is opened directly.
 * Needs the web app, and for Retrieve the real trace store.
 */
const RETRIEVAL_TRACE = "96bca4b5-f707-4a93-b421-2674032849b5";

for (const width of [375, 768, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("five stage cards resolve to five different destinations", async ({
      page,
    }) => {
      await page.goto("/");
      const hrefs: string[] = [];
      for (const title of [
        "Guard",
        "Retrieve",
        "Generate",
        "Judge",
        "Investigate",
      ]) {
        const link = page
          .getByRole("list")
          .getByRole("link", { name: new RegExp(title) })
          .first();
        hrefs.push((await link.getAttribute("href")) ?? "");
      }
      expect(hrefs).toEqual([
        "/overview#flow-heading",
        `/investigations?trace=${RETRIEVAL_TRACE}`,
        "/operations",
        "/architecture#evaluation-plane",
        "/investigations",
      ]);
      expect(new Set(hrefs).size).toBe(5);
    });

    test("Guard opens the reliability pipeline on Overview", async ({
      page,
    }) => {
      await page.goto("/");
      await page
        .getByRole("list")
        .getByRole("link", { name: /Guard/ })
        .first()
        .click();
      await expect(page).toHaveURL(/\/overview#flow-heading$/);
      await expect(
        page.getByRole("heading", { name: "Reliability pipeline" }),
      ).toBeInViewport();
    });

    test("Retrieve opens the persisted execution and its evidence", async ({
      page,
    }) => {
      await page.goto("/");
      await page
        .getByRole("list")
        .getByRole("link", { name: /Retrieve/ })
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp(`trace=${RETRIEVAL_TRACE}`));
      const drawer = page.getByRole("dialog");
      await expect(drawer).toContainText("Amazon");
      await expect(drawer).not.toContainText("Trace not found");
    });

    test("Generate opens Live Operations", async ({ page }) => {
      await page.goto("/");
      await page
        .getByRole("list")
        .getByRole("link", { name: /Generate/ })
        .first()
        .click();
      await expect(page).toHaveURL(/\/operations$/);
      await expect(
        page.getByRole("heading", { level: 1, name: /Live Operations/ }),
      ).toBeVisible();
    });
  });
}

// Opening a stage anchor on the architecture page directly still scrolls to
// that stage and marks it. Nothing on the landing page links here any more.
for (const width of [375, 1440]) {
  test.describe(`architecture anchors at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });
    const suffix = width >= 1024 ? "" : "-outline";

    for (const stage of ["input", "retrieval", "generation"]) {
      test(`#stage-${stage} scrolls to its own stage and marks it`, async ({
        page,
      }) => {
        await page.goto(`/architecture#stage-${stage}${suffix}`);
        const target = page.locator(`#stage-${stage}${suffix}`);
        await expect(target).toBeInViewport({ ratio: 0.5 });
        await expect(page.locator(`[id^="stage-${stage}"]`)).toHaveCount(2);
        await expect(
          page.locator(`[id="stage-${stage}${suffix}"]`),
        ).toHaveCount(1);
        await expect(target.locator("span.bg-accent").first()).toBeVisible();
      });
    }
  });
}
