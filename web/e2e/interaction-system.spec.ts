import { expect, test, type Page } from "@playwright/test";
import { DISAGREEMENT_IS_LIVE } from "./demo-record";

/**
 * The interaction system on Live Operations and Overview, asserted as
 * behavior in a real browser against the real stack (see
 * playwright.config.ts): the pages still populate with real data, hover and
 * focus reveal state without moving the layout, reduced motion removes the
 * rise, in-page links land on real targets, and nothing leaves the page
 * origin or logs an error.
 */

interface Watch {
  problems: string[];
  opsOrigins: Set<string>;
}

function watch(page: Page): Watch {
  const w: Watch = { problems: [], opsOrigins: new Set() };
  page.on("console", (m) => {
    if (m.type() === "error") w.problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => w.problems.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => {
    if (r.failure()?.errorText !== "net::ERR_ABORTED") {
      w.problems.push(`requestfailed: ${r.url()}`);
    }
  });
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/ops/")) w.opsOrigins.add(url.origin);
  });
  return w;
}

/** Where every heading sits in layout terms. offsetTop ignores transforms, so
 * a lift or scale does not register and only a real reflow does. */
function layoutOf(page: Page): Promise<number[]> {
  return page.evaluate(() => [
    document.documentElement.scrollHeight,
    ...[...document.querySelectorAll("h2, h3")].map(
      (el) => (el as HTMLElement).offsetTop,
    ),
  ]);
}

async function openOperations(page: Page) {
  await page.goto("/operations");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Reachable", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
}

test.describe("Live Operations interaction system", () => {
  test("still populates from real data, with real chart bars and no errors", async ({
    page,
  }) => {
    const w = watch(page);
    await openOperations(page);

    const activity = page.getByRole("region", {
      name: "Request activity",
      exact: true,
    });
    await expect(activity.getByText("no data")).toHaveCount(0);

    // The chart opens on stored history, so it has more than one real bar,
    // and each bar names its source in the table view.
    const bars = page.locator("#activity-requests .recharts-bar-rectangle");
    await expect(bars.first()).toBeVisible();
    expect(await bars.count()).toBeGreaterThan(1);
    const live = page.locator("#activity-requests figcaption");
    await expect(live).toContainText(/Live|Not live/);

    expect([...w.opsOrigins]).toEqual(["http://localhost:3000"]);
    expect(w.problems).toEqual([]);
  });

  test("a freshness cell reveals what it rests on by keyboard focus and hides on Escape", async ({
    page,
  }) => {
    await openOperations(page);
    const cells = page.locator(
      "dl[aria-label='Connection and freshness'] > div",
    );
    await expect(cells).toHaveCount(4);

    const first = cells.first();
    await first.focus();
    const peek = first.locator(".peek");
    await expect(peek).toHaveCSS("opacity", "1");
    await expect(peek).toContainText("EventSource");

    await page.keyboard.press("Escape");
    await expect(peek).toHaveCSS("opacity", "0");
  });

  test("every freshness cell and readout link is reachable by Tab with a visible focus indicator", async ({
    page,
  }) => {
    await openOperations(page);
    const seen: string[] = [];
    // Six primary navigation links come before the freshness cells.
    for (let i = 0; i < 13; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const style = getComputedStyle(el);
        return {
          label: (el.textContent ?? "").trim().slice(0, 40),
          outline:
            parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none",
        };
      });
      if (info) {
        seen.push(info.label);
        expect(info.outline, `focus indicator on "${info.label}"`).toBe(true);
      }
    }
    expect(seen.some((l) => l.startsWith("Stream"))).toBe(true);
    expect(seen.some((l) => l.startsWith("Throughput"))).toBe(true);
  });

  test("a readout is a real link: it lands on the chart that draws it", async ({
    page,
  }) => {
    await openOperations(page);
    await page.getByRole("link", { name: /^Throughput/ }).click();
    await expect(page).toHaveURL(/#activity-requests$/);
    await expect(page.locator("#activity-requests")).toBeInViewport();

    await page.getByRole("link", { name: /^p95 latency/ }).click();
    await expect(page).toHaveURL(/#activity-latency$/);
    await expect(page.locator("#activity-latency")).toBeInViewport();
  });

  test("hovering readouts, eval cards and the calibration shell moves nothing around them", async ({
    page,
  }) => {
    await openOperations(page);
    const before = await layoutOf(page);

    const targets = [
      page.getByRole("link", { name: /^Throughput/ }),
      page.locator("section[aria-label='Flash judge, faithfulness']"),
      page.locator("#calibration .instrument"),
    ];
    for (const target of targets) {
      await target.scrollIntoViewIfNeeded();
      const box = await target.boundingBox();
      if (!box) throw new Error("target has no box");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(450);
      expect(await layoutOf(page)).toEqual(before);
    }
  });

  test("the calibration shell rises on hover, and not under reduced motion", async ({
    browser,
  }) => {
    const wake = async (reducedMotion: "reduce" | "no-preference") => {
      const context = await browser.newContext({
        reducedMotion,
        baseURL: "http://localhost:3000",
      });
      const page = await context.newPage();
      await openOperations(page);
      const shell = page.locator("#calibration .instrument");
      await shell.scrollIntoViewIfNeeded();
      await page.waitForTimeout(1200);
      const box = await shell.boundingBox();
      if (!box) throw new Error("shell has no box");
      await page.mouse.move(box.x + 40, box.y + 40);
      await page.waitForTimeout(500);
      const transform = await shell.evaluate(
        (el) => getComputedStyle(el).transform,
      );
      await context.close();
      return transform;
    };
    expect(await wake("no-preference")).not.toBe("none");
    expect(await wake("reduce")).toBe("none");
  });

  test("the kappa figure is the persisted value and does not change under hover", async ({
    page,
  }) => {
    await openOperations(page);
    const kappa = page
      .locator("#calibration .tabular-metric")
      .filter({ hasText: /^\d\.\d{3}$/ })
      .first();
    await kappa.scrollIntoViewIfNeeded();
    const before = await kappa.innerText();
    const shell = page.locator("#calibration .instrument");
    const box = await shell.boundingBox();
    if (!box) throw new Error("shell has no box");
    await page.mouse.move(box.x + 60, box.y + 60);
    await page.waitForTimeout(500);
    expect(await kappa.innerText()).toBe(before);
  });
});

test.describe("Overview interaction system", () => {
  test("still populates with real counts and the Amazon disagreement", async ({
    page,
  }) => {
    const w = watch(page);
    await page.goto("/overview");
    const state = page.getByRole("region", { name: "System state" });
    await expect(state).toBeVisible();
    await expect(state.getByText(/\d+ of \d+/)).toBeVisible();
    if (DISAGREEMENT_IS_LIVE) {
      await expect(page.locator("#featured-heading")).toContainText(/amazon/i);
    } else {
      await expect(page.locator("#featured-heading")).toHaveCount(0);
    }
    expect(w.problems).toEqual([]);
  });

  test("the secondary readouts lead only to destinations that exist", async ({
    page,
  }) => {
    await page.goto("/overview");
    const state = page.getByRole("region", { name: "System state" });

    await expect(page.locator("#coverage-heading")).toHaveCount(1);
    await expect(state.locator("a[href='#coverage-heading']")).toHaveCount(1);

    // The disagreement readout leads to the lens only while a disagreement is stored.
    const disagreement = state.locator(
      "a[href='/investigations?disagreement=true']",
    );
    if (!DISAGREEMENT_IS_LIVE) {
      await expect(disagreement).toHaveCount(0);
      return;
    }
    await expect(disagreement).toHaveCount(1);
    await disagreement.click();
    await expect(page).toHaveURL(/\/investigations\?disagreement=true$/);
    await expect(page.locator("table tbody tr").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("the top condition links to its own real destination", async ({
    page,
  }) => {
    await page.goto("/overview");
    const state = page.getByRole("region", { name: "System state" });
    const link = state
      .locator("a[href^='/investigations'], a[href^='/operations']")
      .first();
    const href = await link.getAttribute("href");
    expect(href).toBeTruthy();
    // The same destination the ranked list below uses for its first item.
    await expect(page.locator(`a[href="${href}"]`).nth(1)).toBeAttached();
  });

  test("the system state field and the featured card respond without reflow", async ({
    page,
  }) => {
    await page.goto("/overview");
    if (DISAGREEMENT_IS_LIVE) {
      await expect(page.locator("#featured-heading")).toBeVisible();
    }
    const before = await layoutOf(page);
    const targets = DISAGREEMENT_IS_LIVE
      ? [".state-field", "#featured-heading"]
      : [".state-field"];
    for (const sel of targets) {
      const target = page.locator(sel).first();
      const box = await target.boundingBox();
      if (!box) throw new Error(`${sel} has no box`);
      await page.mouse.move(box.x + 30, box.y + 30);
      await page.waitForTimeout(450);
      expect(await layoutOf(page)).toEqual(before);
    }
  });
});

test.describe("Decision navigator", () => {
  test("previews a row on hover, keeps keyboard selection and shows one decision at a time", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const rows = page.locator("button[id^='decision-tab-']");
    await rows.first().scrollIntoViewIfNeeded();
    await expect(rows).toHaveCount(6);

    // Hover a row that is not selected: its preview plate appears.
    const third = rows.nth(2);
    await third.hover();
    await page.waitForTimeout(400);
    const plate = third.locator("span[aria-hidden='true']").first();
    await expect(plate).toHaveCSS("opacity", "1");

    // Keyboard selection still moves and exposes only that decision.
    await rows.first().focus();
    await page.keyboard.press("ArrowDown");
    await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");
    await expect(rows.nth(1)).toBeFocused();
    await page.waitForTimeout(700);
    const panels = page.locator("[id^='decision-panel-']");
    const opaque = await panels.evaluateAll(
      (els) => els.filter((el) => getComputedStyle(el).opacity === "1").length,
    );
    expect(opaque).toBe(1);
  });

  test("pointing at a part of the open decision brings it forward and quiets the part beside it", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const rows = page.locator("button[id^='decision-tab-']");
    await rows.first().scrollIntoViewIfNeeded();
    await rows.nth(2).click();
    const panel = page.locator("#decision-panel-2");
    await expect(panel).toHaveCSS("opacity", "1");
    const cards = panel.locator(".dn-focus");
    await expect(cards).toHaveCount(2);

    await expect(cards.nth(0)).toHaveCSS("opacity", "1");
    await expect(cards.nth(1)).toHaveCSS("opacity", "1");
    await cards.nth(0).hover();
    await expect(cards.nth(0)).toHaveCSS("opacity", "1");
    await expect(cards.nth(1)).toHaveCSS("opacity", "0.55");
    await cards.nth(1).hover();
    await expect(cards.nth(0)).toHaveCSS("opacity", "0.55");
    await expect(cards.nth(1)).toHaveCSS("opacity", "1");

    // Moving off the ledger restores both, so nothing stays dimmed.
    await page.mouse.move(5, 5);
    await expect(cards.nth(0)).toHaveCSS("opacity", "1");
    await expect(cards.nth(1)).toHaveCSS("opacity", "1");
  });
});
