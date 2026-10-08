import { expect, test, type Page } from "@playwright/test";

/**
 * Cross-origin guard for the browser -> gateway boundary.
 *
 * Investigations (fetch) and Live Operations (EventSource) call the gateway
 * from client components. The gateway's CORS allowlist names only
 * http://localhost:3000, so any other page origin (127.0.0.1, a LAN address,
 * a phone) is blocked unless the browser stays same-origin. lib/config.ts
 * defaults the browser to "" and next.config.ts rewrites /ops/* to the
 * gateway to make that true.
 *
 * Every other spec in this suite loads from localhost:3000, the one origin
 * CORS happens to allow, so none of them can see this seam break. This spec
 * loads both pages from an origin the gateway does NOT allow. It fails if the
 * rewrite is removed or the browser default goes back to the absolute gateway
 * URL. Requires the real stack (see playwright.config.ts).
 */
const ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"];

interface Watch {
  problems: string[];
  opsRequestOrigins: Set<string>;
}

function watch(page: Page): Watch {
  const w: Watch = { problems: [], opsRequestOrigins: new Set() };
  page.on("console", (msg) => {
    if (msg.type() === "error") w.problems.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => w.problems.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    // Next aborts in-flight RSC prefetches on navigation; those are not
    // failures of the gateway boundary.
    if (req.failure()?.errorText === "net::ERR_ABORTED") return;
    w.problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText}`);
  });
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.pathname.startsWith("/ops/")) w.opsRequestOrigins.add(url.origin);
  });
  return w;
}

for (const origin of ORIGINS) {
  test.describe(`cross-origin guard from ${origin}`, () => {
    test("Investigations renders real trace rows and never leaves the page origin", async ({
      page,
    }) => {
      const w = watch(page);
      await page.goto(`${origin}/investigations`);

      await expect(page.locator("table tbody tr").first()).toBeVisible({
        timeout: 10_000,
      });
      await expect(page.getByText("Failed to fetch")).toHaveCount(0);

      expect([...w.opsRequestOrigins]).toEqual([origin]);
      expect(w.problems).toEqual([]);
    });

    test("Live Operations receives the SSE snapshot and never leaves the page origin", async ({
      page,
    }) => {
      const w = watch(page);
      await page.goto(`${origin}/operations`);

      await expect(page.getByText("Connected", { exact: true })).toBeVisible({
        timeout: 10_000,
      });
      await expect(page.getByText("Reachable", { exact: true })).toBeVisible({
        timeout: 10_000,
      });
      const activity = page.getByRole("region", { name: "Request activity" });
      await expect(
        activity.getByText("Throughput", { exact: true }),
      ).toBeVisible();
      await expect(activity.getByText("no data")).toHaveCount(0);

      expect([...w.opsRequestOrigins]).toEqual([origin]);
      expect(w.problems).toEqual([]);
    });
  });
}
