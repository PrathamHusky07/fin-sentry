import { expect, test, type Page } from "@playwright/test";

/**
 * "Reading a case file" on /agent: seven states in two bands. The border style of each tile is
 * its meaning, so the test reads the computed style in the browser: solid for what says
 * something about the platform, dashed for what says nothing. Pointing or focusing brings a
 * state forward and quiets the rest, a click or Enter keeps it, and reduced motion keeps the
 * state without the lift. It reads no gateway data and starts nothing.
 */

const SOLID = ["returned", "verified_empty", "hypothesis"];
const DASHED = ["unverified_empty", "unavailable", "rejected", "abstained"];
const LABEL: Record<string, string> = {
  returned: "Returned records",
  verified_empty: "Ran, matched nothing",
  hypothesis: "Best-supported hypothesis",
  unverified_empty: "Empty, not verified",
  unavailable: "Could not run",
  rejected: "Rejected",
  abstained: "Abstained",
};

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

const tile = (page: Page, id: string) =>
  page.locator(`#guide [data-reading="${id}"]`);

test.describe("wide", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the border style of each state is its meaning", async ({ page }) => {
    await page.goto("/agent");
    await expect(page.locator("#guide [data-reading]")).toHaveCount(7);
    for (const id of SOLID) {
      await expect(tile(page, id)).toHaveCSS("border-top-style", "solid");
    }
    for (const id of DASHED) {
      await expect(tile(page, id)).toHaveCSS("border-top-style", "dashed");
    }
    // The two bands are named by the same rule.
    await expect(page.locator("#guide")).toContainText(
      "Says something about the platform",
    );
    await expect(page.locator("#guide")).toContainText(
      "Says nothing about the platform",
    );
  });

  test("pointing brings a state forward, quiets the rest and shows what it means", async ({
    page,
  }) => {
    const seen = watch(page);
    await page.goto("/agent");
    const panel = page.locator("#reading-detail");
    // At rest the kept state is forward and the others are quiet.
    await expect(tile(page, "returned")).toHaveAttribute(
      "data-state",
      "active",
    );
    await expect(tile(page, "rejected")).toHaveAttribute("data-state", "quiet");
    await expect(panel).toHaveAttribute("aria-label", LABEL.returned);

    await tile(page, "unavailable").hover();
    await expect(tile(page, "unavailable")).toHaveAttribute(
      "data-state",
      "active",
    );
    await expect(tile(page, "returned")).toHaveAttribute("data-state", "quiet");
    await expect(panel).toHaveAttribute("aria-label", LABEL.unavailable);
    await expect(panel).toContainText("says nothing about the platform");
    await expect(panel).toContainText("Says nothing about the platform");
    await expect(panel).toContainText("Preview. Click or press Enter");
    // A preview is not a selection.
    await expect(tile(page, "returned")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(tile(page, "unavailable")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    // Leaving restores the kept state. Clicking keeps a new one.
    await page.mouse.move(2, 2);
    await expect(panel).toHaveAttribute("aria-label", LABEL.returned);
    await tile(page, "hypothesis").click();
    await page.mouse.move(2, 2);
    await expect(panel).toHaveAttribute("aria-label", LABEL.hypothesis);
    await expect(panel).toContainText("not a proven cause");
    await expect(panel).toContainText("Says something about the platform");
    await expect(tile(page, "hypothesis")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });

  test("the keyboard mirrors the pointer: arrows preview, Enter keeps", async ({
    page,
  }) => {
    await page.goto("/agent");
    const panel = page.locator("#reading-detail");
    await tile(page, "returned").focus();
    await page.keyboard.press("ArrowRight");
    await expect(tile(page, "verified_empty")).toBeFocused();
    await expect(panel).toHaveAttribute("aria-label", LABEL.verified_empty);
    await expect(tile(page, "returned")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.keyboard.press("Enter");
    await expect(tile(page, "verified_empty")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Arrows run through every state in reading order and wrap at the ends.
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await expect(tile(page, "abstained")).toBeFocused();
    await expect(panel).toHaveAttribute("aria-label", LABEL.abstained);
    await expect(panel).toContainText("complete result");
  });

  test("reduced motion keeps the state and removes the lift", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/agent");
    await tile(page, "rejected").click();
    await expect(tile(page, "rejected")).toHaveAttribute(
      "data-state",
      "active",
    );
    await expect(tile(page, "rejected")).toHaveCSS("transform", "none");
  });
});

test.describe("narrow", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("the kept state opens in place and only one is open", async ({
    page,
  }) => {
    await page.goto("/agent");
    await expect(page.locator("#guide [aria-expanded='true']")).toHaveCount(1);
    await expect(tile(page, "returned")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await tile(page, "abstained").click();
    await expect(tile(page, "abstained")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(tile(page, "returned")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await expect(page.locator("#guide #reading-detail")).toHaveCount(1);
    await expect(
      page.locator('#guide li:has([data-reading="abstained"])'),
    ).toContainText("complete result");
  });
});

for (const width of [375, 768, 1024, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("fits the screen and every state is a target of at least 44px", async ({
      page,
    }) => {
      const seen = watch(page);
      await page.goto("/agent");
      await page.locator("#guide").scrollIntoViewIfNeeded();
      for (const id of [...SOLID, ...DASHED]) {
        const box = await tile(page, id).boundingBox();
        expect(box?.height ?? 0, id).toBeGreaterThanOrEqual(44);
        expect(box?.width ?? 0, id).toBeGreaterThanOrEqual(44);
      }
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(seen.issues).toEqual([]);
    });
  });
}
