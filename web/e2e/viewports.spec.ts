import { expect, test, type Page } from "@playwright/test";

/**
 * The rebuilt Agent and Red Team pages at the four widths the project reviews: 375, 768, 1024
 * and 1440. Each page is opened, one interactive state is exercised, and the page is checked
 * for horizontal overflow, small targets, console errors and exactly one footer. Reads only.
 */

const WIDTHS = [375, 768, 1024, 1440];

function watch(page: Page) {
  const issues: string[] = [];
  const posts: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") issues.push(m.text());
  });
  page.on("pageerror", (e) => issues.push(e.message));
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  return { issues, posts };
}

async function audit(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow, "horizontal overflow").toBeLessThanOrEqual(0);
  const small = await page.evaluate(() =>
    [
      ...document.querySelectorAll(
        "main a, main button, main summary, main select, main input, footer a",
      ),
    ]
      .filter((e) => {
        const b = e.getBoundingClientRect();
        return (
          b.width > 0 &&
          b.height > 0 &&
          !e.closest("svg") &&
          !e.classList.contains("sr-only") &&
          !(e instanceof HTMLInputElement && e.type === "checkbox") &&
          (b.height < 43.5 || b.width < 43.5)
        );
      })
      .map((e) => e.textContent?.trim().slice(0, 30)),
  );
  expect(small, "targets under 44px").toEqual([]);
  await expect(page.getByRole("contentinfo")).toHaveCount(1);
}

for (const width of WIDTHS) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("/agent: the map, a selected stage, a selected case and the record states", async ({
      page,
    }) => {
      const seen = watch(page);
      await page.goto("/agent");
      await page.waitForLoadState("networkidle");
      const wide = width >= 1024;
      const stage = wide
        ? page.locator('#lifecycle [role="button"]').nth(3)
        : page.locator("#lifecycle ol > li > button").nth(3);
      await stage.click();
      await expect(page.locator("#agent-step-detail")).toContainText("Assess");
      await page
        .locator("#investigations ul li.row-reveal button")
        .nth(1)
        .click();
      await expect(
        page.locator("#investigations article").first(),
      ).toContainText("Open the case file");
      await expect(page.locator("#records [data-record-state]")).toHaveCount(4);
      await audit(page);
      expect(seen.posts).toEqual([]);
      expect(seen.issues).toEqual([]);
    });

    test("a case file: three layers, a selected hypothesis and the evidence trail", async ({
      page,
      request,
    }) => {
      const list = (await (
        await request.get("/ops/investigations?limit=50")
      ).json()) as {
        investigations: {
          investigation_id: string;
          outcome: string | null;
          origin: string;
        }[];
      };
      const row = list.investigations.find(
        (r) => r.origin === "fixture" && r.outcome === "diagnosis",
      );
      if (!row) throw new Error("Seed the fixture sessions first.");
      const seen = watch(page);
      await page.goto(`/agent/${row.investigation_id}`);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("[aria-label^='Layer ']")).toHaveCount(3);
      await page.locator("#hypotheses ol > li button").nth(1).click();
      await expect(page.locator("#hypotheses")).toContainText(
        "Rival explanations (",
      );
      await audit(page);
      expect(seen.issues).toEqual([]);
      expect(seen.posts).toEqual([]);
    });

    test("/red-team: the filters, a selected scenario, the collapsed history and workflow", async ({
      page,
    }) => {
      const seen = watch(page);
      await page.goto("/red-team");
      await expect(page.locator("[data-scenario]").first()).toBeVisible({
        timeout: 15_000,
      });
      await page
        .locator('[data-scenario="HZ-001"] button[aria-expanded]')
        .click();
      await expect(page.getByRole("article", { name: /HZ-001/ })).toBeVisible();
      await page.getByRole("button", { name: /^Completed/ }).click();
      await expect(page.locator("#history-body")).toHaveCount(0);
      await expect(page.locator("#execute-body")).toHaveCount(0);
      await audit(page);
      expect(seen.posts).toEqual([]);
      expect(seen.issues).toEqual([]);
    });

    test("/ has one footer and /overview, /operations, /investigations, /architecture are not widened by it", async ({
      page,
    }) => {
      for (const route of [
        "/",
        "/overview",
        "/operations",
        "/investigations",
        "/architecture",
      ]) {
        await page.goto(route);
        await expect(page.getByRole("contentinfo")).toHaveCount(1);
        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        );
        expect(overflow, `${route} overflow`).toBeLessThanOrEqual(0);
      }
    });
  });
}
