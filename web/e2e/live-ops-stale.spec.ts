import { expect, test } from "@playwright/test";

/**
 * Live Operations in a quiet period. When the newest stored bucket is stale the chart shows the
 * last activity that was actually recorded, with its real date and time, and says it is not the
 * last hour. When traffic is current it keeps the "last hour" heading. Which of the two applies
 * is read from the gateway's own stored buckets, so the test follows the data and does not
 * assume a quiet system. It asserts no bar is invented: every plotted bucket is a stored one.
 * Needs the stack running.
 */

interface History {
  buckets: { window_start: string; window_end: string }[];
}

const STALE_AFTER_MS = 2 * 60_000;

function utc(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${month} ${d.getUTCDate()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

for (const width of [375, 768, 1024, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("a stale series is labeled with its real time and a current one keeps the last-hour heading", async ({
      page,
      request,
    }) => {
      const issues: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error" || m.type() === "warning")
          issues.push(m.text());
      });
      const res = await request.get("/ops/metrics/throughput/history?limit=60");
      expect(res.ok()).toBeTruthy();
      const { buckets } = (await res.json()) as History;
      test.skip(
        buckets.length === 0,
        "No stored bucket exists, so there is no series to label.",
      );
      const newest = buckets[buckets.length - 1].window_end;

      await page.goto("/operations");
      const section = page.locator("section[aria-labelledby='chart-heading']");
      await expect(section).toBeVisible();
      const stale = Date.now() - new Date(newest).getTime() > STALE_AFTER_MS;

      if (stale) {
        await expect(
          section.getByRole("heading", { name: "Last recorded activity" }),
        ).toBeVisible();
        // The real time of the newest stored bucket, and its age.
        await expect(section).toContainText(`since ${utc(newest)}`);
        await expect(section).toContainText(
          `Last recorded activity ended ${utc(newest)}`,
        );
        await expect(section).toContainText("They are not from the last hour");
        await expect(section).not.toContainText("Request buckets, last hour");

        // The table lists dated stored buckets only, none of them live, newest as stored.
        await section.getByText("View the buckets as a table").click();
        const rows = section.locator("table tbody tr");
        const count = await rows.count();
        expect(count).toBeGreaterThan(0);
        expect(count).toBeLessThanOrEqual(buckets.length);
        await expect(section.locator("table")).not.toContainText("Live bucket");
        const lastRow = await rows.last().innerText();
        const end = new Date(newest);
        const month = end.toLocaleString("en-US", {
          month: "short",
          timeZone: "UTC",
        });
        expect(lastRow).toContain(`${month} ${end.getUTCDate()}`);
      } else {
        await expect(
          section.getByRole("heading", { name: "Request buckets, last hour" }),
        ).toBeVisible();
        await expect(section).not.toContainText("Last recorded activity");
      }

      // Fits the screen, and every control is at least 44px tall.
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
