import { expect, test } from "@playwright/test";

/**
 * Staleness on Live Operations. The request-bucket chart this file used to cover is gone, and
 * the same honesty now lives in two places: each evaluation card carries a stale flag from the
 * snapshot and must say "Stale" exactly when the flag is set, and the "Newest recorded request"
 * line dates the data behind a stale card with the real timestamp of the newest stored trace.
 * The test follows the data and does not assume a quiet or a busy system. It also holds the
 * page to no horizontal overflow and a clean console at four widths. Needs the stack running.
 */

interface TraceList {
  traces: { timestamp_utc: string; app_trace_id: string }[];
}

function utc(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${month} ${d.getUTCDate()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

for (const width of [375, 768, 1024, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("a stale card says so, a current one does not, and the newest request is dated truthfully", async ({
      page,
      request,
    }) => {
      const issues: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error" || m.type() === "warning")
          issues.push(m.text());
      });
      const res = await request.get("/ops/traces?limit=1");
      expect(res.ok()).toBeTruthy();
      const { traces } = (await res.json()) as TraceList;

      await page.goto("/operations");
      const telemetry = page.locator("section[aria-labelledby='eval-heading']");
      const cards = telemetry.locator("section[data-stale]");
      await expect(cards).toHaveCount(4);
      await expect(telemetry.getByText(/ended .* UTC/).first()).toBeVisible({
        timeout: 10_000,
      });

      // Every card: the flag and the word agree. A stale card never reads as current.
      for (let i = 0; i < 4; i += 1) {
        const card = cards.nth(i);
        const stale = (await card.getAttribute("data-stale")) === "true";
        const header = card.locator("p").first();
        if (stale) {
          await expect(header).toContainText("Stale");
        } else {
          await expect(card).not.toContainText("Stale");
        }
      }

      // The newest recorded request carries the real timestamp of the newest stored trace.
      const newest = page.getByText(/^Newest recorded request /);
      if (traces.length === 0) {
        await expect(newest).toHaveCount(0);
      } else {
        await expect(newest).toContainText(utc(traces[0].timestamp_utc));
        await expect(
          page.getByRole("link", { name: "Open it" }),
        ).toHaveAttribute(
          "href",
          `/investigations?trace=${traces[0].app_trace_id}`,
        );
      }

      // Nothing from the removed chart comes back as a stale-period label.
      await expect(page.getByText("Last recorded activity")).toHaveCount(0);
      await expect(page.getByText("Request buckets, last hour")).toHaveCount(0);

      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(issues).toEqual([]);
    });
  });
}
