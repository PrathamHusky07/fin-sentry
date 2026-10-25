import { expect, test } from "@playwright/test";

/**
 * Every page that reads the archive, at the four widths the project reviews. Structural checks:
 * no horizontal overflow, no standalone control under 44 px, no console error or warning, no
 * request that leaves the site, and no page-level archive line. Run against
 * the archived production build on :3100 (see playwright.config.ts).
 */
const ROUTES = [
  "/overview",
  "/operations",
  "/investigations",
  "/agent",
  "/agent/43751b14-b080-4f5b-8391-33b914f12f22",
  "/red-team",
  "/generation",
];
const WIDTHS = [375, 768, 1024, 1440];

for (const width of WIDTHS) {
  test.describe(`archived pages at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const route of ROUTES) {
      test(`${route} fits`, async ({ page }) => {
        const problems: string[] = [];
        page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
        page.on("console", (m) => {
          if (m.type() === "error" || m.type() === "warning") {
            problems.push(`console: ${m.text()}`);
          }
        });
        page.on("request", (r) => {
          if (new URL(r.url()).origin !== "http://localhost:3100") {
            problems.push(`left the site: ${r.url()}`);
          }
        });

        await page.goto(route);
        await expect(page.locator("[data-archive-notice]")).toHaveCount(0);
        await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
        await page.waitForTimeout(800);

        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        );
        expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);

        // Standalone controls are at least 44 px in both dimensions. Links inside running
        // prose are exempt, as in WCAG 2.5.8, and so is the skip link while it is hidden.
        const small = await page.evaluate(() => {
          const out: string[] = [];
          const nodes = document.querySelectorAll<HTMLElement>(
            "button, a[href], select, input:not([type=hidden])",
          );
          for (const el of nodes) {
            const box = el.getBoundingClientRect();
            if (box.width === 0 || box.height === 0) continue;
            if (el.closest("p, dd, dt, li > p") && el.tagName === "A") continue;
            if (el.closest("svg")) continue;
            if (el.classList.contains("sr-only")) continue;
            if (box.height < 43.5 || box.width < 43.5) {
              out.push(
                `${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 30)}" ${Math.round(box.width)}x${Math.round(box.height)}`,
              );
            }
          }
          return out;
        });
        expect(small, "controls under 44px").toEqual([]);
        expect(problems).toEqual([]);
      });
    }
  });
}
