import { expect, test } from "@playwright/test";

/**
 * One compact footer, rendered by the root layout, on every route. It holds the mark, one
 * line of positioning, the author and a LinkedIn link, and no route navigation (the top bar
 * owns that). Needs only the web app.
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

const LINKEDIN = "https://www.linkedin.com/in/prathameshkulkarni23/";

for (const width of [375, 768, 1024, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const route of ROUTES) {
      test(`${route} has exactly one compact footer with a LinkedIn link`, async ({
        page,
      }) => {
        await page.goto(route);
        const footer = page.getByRole("contentinfo");
        await expect(footer).toHaveCount(1);
        await expect(footer).toContainText(
          "Reliability and evaluation for production LLM systems.",
        );
        await expect(footer).toContainText("© 2026 Prathamesh Kulkarni");
        await expect(footer.getByRole("navigation")).toHaveCount(0);

        const linkedin = footer.getByRole("link", { name: /LinkedIn/ });
        await expect(linkedin).toHaveText("LinkedIn");
        await expect(linkedin).toHaveAttribute("href", LINKEDIN);
        await expect(linkedin).toHaveAttribute("target", "_blank");
        await expect(linkedin).toHaveAttribute("rel", /noopener/);

        for (const link of await footer.getByRole("link").all()) {
          const box = await link.boundingBox();
          expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
        }
        // One row of content, not a two-tier block.
        const box = await footer.boundingBox();
        expect(box?.height ?? 0).toBeLessThan(
          width < 640 ? 190 : width < 1024 ? 135 : 80,
        );
        expect(
          await page.evaluate(
            () =>
              document.documentElement.scrollWidth <=
              document.documentElement.clientWidth,
          ),
        ).toBe(true);
      });
    }
  });
}

test("the footer repeats no route link and its internal link opens a page", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const hrefs = await page
    .getByRole("contentinfo")
    .getByRole("link")
    .evaluateAll((els) => els.map((el) => el.getAttribute("href") ?? ""));
  expect(hrefs).toEqual(["/", LINKEDIN]);
  const response = await request.get("/");
  expect(response.status()).toBe(200);
});
