import { expect, test, type Locator, type Page } from "@playwright/test";

/** A stage card's link, found inside the card list so the top bar's and the footer's links of
 * the same name cannot satisfy it. */
function stageLink(page: Page, title: string): Locator {
  return page
    .getByRole("list")
    .filter({ has: page.getByRole("heading", { name: "Guard", exact: true }) })
    .getByRole("link", { name: new RegExp(`^${title}`) });
}

/**
 * The landing stage cards each open their own destination. Guard opens the blocked requests,
 * Retrieve and Generate open their own stages on the architecture page (the only place either
 * is explained), Judge opens the evaluation coverage, Agent opens the Agent, and Red Team is a
 * separate line that opens its own route. The wide pipeline and the narrow outline each carry
 * their own copy of a stage id, so the Retrieve and Generate landings have to be displayed
 * elements at the width under test. Needs only the web app.
 */
for (const width of [375, 768, 1024, 1440]) {
  const suffix = width >= 1024 ? "" : "-outline";
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("five stage cards resolve to five different real destinations", async ({
      page,
    }) => {
      await page.goto("/");
      const expected = [
        "/investigations?status=blocked",
        `/architecture#stage-retrieval${suffix}`,
        `/architecture#stage-generation${suffix}`,
        "/overview#coverage-heading",
        "/agent",
      ];
      const titles = ["Guard", "Retrieve", "Generate", "Judge", "Agent"];
      // The wide ids replace the outline ids once the page hydrates, so each href is
      // asserted with retries.
      for (const [i, title] of titles.entries()) {
        await expect(stageLink(page, title)).toHaveAttribute(
          "href",
          expected[i],
        );
      }
      // Five different destinations. Retrieve and Generate have no product view, so they are
      // two different stages of the same architecture page.
      expect(new Set(expected).size).toBe(5);
      const routes = expected.map((href) => href.split(/[?#]/)[0]);
      expect(routes.filter((r) => r === "/architecture")).toHaveLength(2);
      await expect(page.getByText("Investigate", { exact: true })).toHaveCount(
        0,
      );
    });

    test("Guard opens the blocked requests, filtered", async ({ page }) => {
      await page.goto("/");
      await stageLink(page, "Guard").click();
      await expect(page).toHaveURL(/\/investigations\?status=blocked/);
      await expect(
        page.getByRole("heading", { level: 1, name: "Investigations" }),
      ).toBeVisible();
    });

    test("Retrieve lands on its own displayed stage", async ({ page }) => {
      await page.goto("/");
      await stageLink(page, "Retrieve").click();
      await expect(page).toHaveURL(
        new RegExp(`/architecture#stage-retrieval${suffix}$`),
      );
      const target = page.locator(`#stage-retrieval${suffix}`);
      await expect(target).toBeVisible();
      await expect(target).toBeInViewport({ ratio: 0.5 });
    });

    test("Generate lands on its own displayed stage, which states the bounds", async ({
      page,
    }) => {
      await page.goto("/");
      await stageLink(page, "Generate").click();
      await expect(page).toHaveURL(
        new RegExp(`/architecture#stage-generation${suffix}$`),
      );
      const target = page.locator(`#stage-generation${suffix}`);
      await expect(target).toBeVisible();
      await expect(target).toBeInViewport({ ratio: 0.5 });
    });

    test("Judge opens the evaluation coverage", async ({ page }) => {
      await page.goto("/");
      await stageLink(page, "Judge").click();
      await expect(page).toHaveURL(/\/overview#coverage-heading$/);
      await expect(
        page.getByRole("heading", { name: "Evaluation coverage" }),
      ).toBeInViewport();
    });

    test("Agent opens the Agent route", async ({ page }) => {
      await page.goto("/");
      await stageLink(page, "Agent").click();
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
