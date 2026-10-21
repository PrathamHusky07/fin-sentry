import { expect, test } from "@playwright/test";

/**
 * One footer, rendered by the root layout, on every route. Its links are the same routes as
 * the top bar and each one has to open a page. Needs only the web app for the footer itself.
 */
const ROUTES = [
  "/",
  "/overview",
  "/operations",
  "/investigations",
  "/agent",
  "/architecture",
  "/red-team",
];

for (const width of [375, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const route of ROUTES) {
      test(`${route} has exactly one footer with the six product links`, async ({
        page,
      }) => {
        await page.goto(route);
        await expect(page.getByRole("contentinfo")).toHaveCount(1);
        const links = page
          .getByRole("contentinfo")
          .getByRole("navigation", { name: "Footer" })
          .getByRole("link");
        await expect(links).toHaveText([
          "Overview",
          "Live Operations",
          "Investigations",
          "Agent",
          "Architecture",
          "Red Team",
        ]);
        for (const link of await links.all()) {
          const box = await link.boundingBox();
          expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
        }
      });
    }
  });
}

test("every footer link opens a page", async ({ page, request }) => {
  await page.goto("/");
  const hrefs = await page
    .getByRole("contentinfo")
    .getByRole("link")
    .evaluateAll((els) => els.map((el) => el.getAttribute("href") ?? ""));
  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs) {
    const response = await request.get(href);
    expect(response.status(), href).toBe(200);
  }
});
