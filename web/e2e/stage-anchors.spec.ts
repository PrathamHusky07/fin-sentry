import { expect, test } from "@playwright/test";

/**
 * The first three landing stage cards each open a different stage of the
 * request path on /architecture. The wide pipeline (lg and up) and the
 * narrow outline carry different ids, so the card picks the one the
 * viewport actually shows. Needs only the web app.
 */
const CARDS = [
  { card: /Guard/, stage: "input" },
  { card: /Retrieve/, stage: "retrieval" },
  { card: /Generate/, stage: "generation" },
] as const;

for (const width of [375, 768, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });
    const suffix = width >= 1024 ? "" : "-outline";

    test("three stage cards resolve to three different stage anchors", async ({
      page,
    }) => {
      await page.goto("/");
      const hrefs: string[] = [];
      for (const { card, stage } of CARDS) {
        const link = page
          .getByRole("list")
          .getByRole("link", { name: card })
          .first();
        // The server renders the narrow href; hydration settles on the real one.
        await expect(link).toHaveAttribute(
          "href",
          `/architecture#stage-${stage}${suffix}`,
        );
        hrefs.push((await link.getAttribute("href")) ?? "");
      }
      expect(new Set(hrefs).size).toBe(3);
    });

    for (const { card, stage } of CARDS) {
      test(`${stage} card scrolls to its own stage and marks it`, async ({
        page,
      }) => {
        await page.goto("/");
        const link = page
          .getByRole("list")
          .getByRole("link", { name: card })
          .first();
        await expect(link).toHaveAttribute(
          "href",
          `/architecture#stage-${stage}${suffix}`,
        );
        await link.click();
        await expect(page).toHaveURL(
          new RegExp(`/architecture#stage-${stage}${suffix}$`),
        );
        const target = page.locator(`#stage-${stage}${suffix}`);
        await expect(target).toBeInViewport({ ratio: 0.5 });
        // Exactly one element carries the id, so the other variant never
        // competes for the link.
        await expect(page.locator(`[id^="stage-${stage}"]`)).toHaveCount(2);
        await expect(
          page.locator(`[id="stage-${stage}${suffix}"]`),
        ).toHaveCount(1);
        // The targeted stage is visibly marked, and no other stage is.
        const marked = target.locator("span.bg-accent").first();
        await expect(marked).toBeVisible();
      });
    }
  });
}
