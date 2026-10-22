import { expect, test } from "@playwright/test";
import { RERUN_TRACE_ID } from "./demo-record";

/**
 * One sequential pass over every route at the three widths the project
 * verifies. Structural checks only: no horizontal overflow, exactly one h1,
 * no console errors, no failed data requests, no dev host or repo path in
 * the visible text, controls at least 44 px, a visible focus indicator and
 * the drawer's keyboard containment. Real stack required for the data
 * routes. One browser at a time, by the project's resource-safety rule.
 */
const ROUTES = [
  "/",
  "/overview",
  "/operations",
  "/investigations",
  "/architecture",
  "/agent",
  "/red-team",
];
const WIDTHS = [375, 768, 1440];

for (const width of WIDTHS) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const route of ROUTES) {
      test(`${route} is sound`, async ({ page }) => {
        const problems: string[] = [];
        page.on("pageerror", (e) => problems.push(`pageerror: ${e}`));
        page.on("console", (m) => {
          if (m.type() === "error") problems.push(`console: ${m.text()}`);
        });
        page.on("requestfailed", (r) => {
          const url = r.url();
          if (!url.includes("_rsc=") && !url.includes("/ops/stream")) {
            problems.push(`requestfailed: ${url}`);
          }
        });

        await page.goto(route);
        await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
        await page.waitForTimeout(800);

        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        );
        expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(0);

        const text = await page.locator("body").innerText();
        expect(text).not.toMatch(/localhost|127\.0\.0\.1|:3000|:8000/);
        expect(text).not.toMatch(/finsentry\/|docs\/adr|\.py\b/);

        // Standalone controls are at least 44 px in both dimensions. Links
        // inside running prose are exempt, as in WCAG 2.5.8.
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

        // Keyboard: ten tab stops each show a visible focus indicator.
        for (let i = 0; i < 10; i++) {
          await page.keyboard.press("Tab");
          const visible = await page.evaluate(() => {
            const el = document.activeElement as HTMLElement | null;
            if (!el || el === document.body) return true;
            const cs = getComputedStyle(el);
            if (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) {
              return true;
            }
            // SVG nodes draw their own ring or state change.
            return el.closest("svg") !== null || el.tagName === "SUMMARY";
          });
          expect(visible, `tab stop ${i + 1} has a focus indicator`).toBe(true);
        }

        expect(problems).toEqual([]);
      });
    }

    test("the trace drawer contains focus and closes on Escape", async ({
      page,
    }) => {
      // Any stored trace opens the drawer. The re-asked Amazon trace is a real one.
      await page.goto(`/investigations?trace=${RERUN_TRACE_ID}`);
      const dialog = page.getByRole("dialog", { name: "Trace detail" });
      await expect(dialog).toBeVisible();
      for (let i = 0; i < 30; i++) {
        await page.keyboard.press("Tab");
        const inside = await page.evaluate(() =>
          Boolean(
            document.activeElement?.closest("[role='dialog']") ||
            document.activeElement === document.body,
          ),
        );
        expect(inside, `tab ${i + 1} stays in the drawer`).toBe(true);
      }
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    });
  });
}
