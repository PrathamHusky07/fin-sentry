import { expect, test } from "@playwright/test";

/**
 * The landing stage cards each open the part of the product that shows their stage.
 * Guard, Retrieve and Generate open their request-path stage on the architecture page, Judge
 * opens the evaluation plane, Agent opens the Agent, and Red Team is a separate line that
 * opens its own route. The wide pipeline and the narrow outline each carry their own copy of
 * a stage id, so every landing has to be a displayed element at the width under test. Needs
 * only the web app.
 */
for (const width of [375, 768, 1024, 1440]) {
  const suffix = width >= 1024 ? "" : "-outline";
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("five stage cards resolve to five different real destinations", async ({
      page,
    }) => {
      await page.goto("/");
      const hrefs: string[] = [];
      for (const title of ["Guard", "Retrieve", "Generate", "Judge", "Agent"]) {
        const link = page
          .getByRole("list")
          .getByRole("link", { name: new RegExp(title) })
          .first();
        hrefs.push((await link.getAttribute("href")) ?? "");
      }
      expect(hrefs).toEqual([
        `/architecture#stage-input${suffix}`,
        `/architecture#stage-retrieval${suffix}`,
        `/architecture#stage-generation${suffix}`,
        "/architecture#evaluation-plane",
        "/agent",
      ]);
      expect(new Set(hrefs).size).toBe(5);
      await expect(page.getByText("Investigate", { exact: true })).toHaveCount(
        0,
      );
    });

    for (const [title, stage] of [
      ["Guard", "input"],
      ["Retrieve", "retrieval"],
      ["Generate", "generation"],
    ] as const) {
      test(`${title} lands on its own displayed stage`, async ({ page }) => {
        await page.goto("/");
        await page
          .getByRole("list")
          .getByRole("link", { name: new RegExp(title) })
          .first()
          .click();
        await expect(page).toHaveURL(
          new RegExp(`/architecture#stage-${stage}${suffix}$`),
        );
        const target = page.locator(`#stage-${stage}${suffix}`);
        await expect(target).toBeVisible();
        await expect(target).toBeInViewport({ ratio: 0.5 });
      });
    }

    test("Judge opens the evaluation plane", async ({ page }) => {
      await page.goto("/");
      await page
        .getByRole("list")
        .getByRole("link", { name: /Judge/ })
        .first()
        .click();
      await expect(page).toHaveURL(/\/architecture#evaluation-plane$/);
      await expect(
        page.getByRole("heading", { name: "Evaluation plane" }),
      ).toBeInViewport();
    });

    test("Agent opens the Agent route", async ({ page }) => {
      await page.goto("/");
      await page
        .getByRole("list")
        .getByRole("link", { name: /Agent/ })
        .first()
        .click();
      await expect(page).toHaveURL(/\/agent$/);
      await expect(
        page.getByRole("heading", {
          level: 1,
          name: /Incident Response Agent/,
        }),
      ).toBeVisible();
    });

    test("Red Team is its own line, outside the numbered stages", async ({
      page,
    }) => {
      await page.goto("/");
      const stages = page.getByRole("list").filter({ hasText: "Guard" });
      await expect(stages.getByRole("link", { name: /Red Team/ })).toHaveCount(
        0,
      );
      await expect(page.getByText("Outside the request path.")).toBeVisible();
      await page.getByRole("link", { name: /Open Red Team/ }).click();
      await expect(page).toHaveURL(/\/red-team$/);
      await expect(
        page.getByRole("heading", { level: 1, name: "Red Team" }),
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
