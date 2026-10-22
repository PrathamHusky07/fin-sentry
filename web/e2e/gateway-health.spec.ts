import { expect, test } from "@playwright/test";

/**
 * Live Operations shows three different latencies and must never let one pass for another. The
 * recorded gateway probe is a stored reading of the health route. The page's own check times the
 * same route once per visit and stores nothing. The metrics buckets time whole RAG queries. The
 * health route runs no retrieval and no model. Needs the gateway, because it serves the probe.
 */
test.use({ viewport: { width: 1440, height: 900 } });

test("the recorded gateway probe is primary, dated and labeled as not RAG latency", async ({
  page,
}) => {
  const issues: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(m.text());
  });
  await page.goto("/operations");

  const probe = page.locator("[data-gateway-probe]");
  await expect(probe).toHaveAttribute("data-gateway-probe", "recorded");
  await expect(probe).toContainText("Gateway round trip, recorded probe");
  await expect(probe).toContainText("runs no retrieval and no model");
  await expect(probe).toContainText("not RAG latency");
  await expect(probe).toContainText("It is stored");
  const text = await probe.innerText();
  expect(text).toMatch(/Recorded \w{3} \d+, \d{2}:\d{2} UTC/);
  const median = Number(text.match(/([\d.]+)\s*ms median/)?.[1]);
  expect(median).toBeGreaterThan(0);
  expect(median).toBeLessThan(1000);
  expect(text).toMatch(/\d+ requests/);

  // The probe sits above the RAG readouts, and the readouts never claim its number.
  const probeBox = await probe.boundingBox();
  const readouts = page.locator("#activity-heading + dl");
  const readoutsBox = await readouts.boundingBox();
  expect(probeBox && readoutsBox && probeBox.y < readoutsBox.y).toBe(true);
  await expect(readouts).toContainText("RAG queries recorded");
  await expect(readouts).toContainText("End-to-end RAG (local model)");
  await expect(readouts).toContainText("retrieval and generation included");
  await expect(readouts).not.toContainText("Gateway round trip");
  await expect(readouts).not.toContainText("Gateway health check");
  expect(issues).toEqual([]);
});

test("the page's own health check is bounded, separate and not stored", async ({
  page,
}) => {
  await page.goto("/operations");

  const check = page.locator("[data-gateway-health]");
  await expect(check).toHaveAttribute("data-gateway-health", "measured");
  await expect(check).toContainText("Checked just now by this page");
  await expect(check).toContainText("not stored");
  await expect(check).toContainText("not request latency");
  const ms = Number(
    (await check.innerText()).match(/this page\s*([\d.]+) ms/)?.[1],
  );
  expect(ms).toBeGreaterThan(0);
  expect(ms).toBeLessThan(1500);
});

test("every stored bucket reports one p95 over the same requests as its average", async ({
  page,
  request,
}) => {
  const res = await request.get("/ops/metrics/throughput/history?limit=500");
  expect(res.ok()).toBe(true);
  const body = (await res.json()) as {
    buckets: {
      total_requests: number;
      avg_latency_ms: number | null;
      p95_latency_ms: number | null;
    }[];
  };
  const compared = body.buckets.filter(
    (b) => b.p95_latency_ms !== null && b.avg_latency_ms !== null,
  );
  expect(compared.length).toBeGreaterThan(0);
  for (const b of compared) {
    // With at most 20 requests a continuous 95th percentile is never below the mean. A larger
    // bucket can legitimately sit under it when one value dominates, so it is not asserted.
    if (b.total_requests <= 20) {
      expect(b.p95_latency_ms as number).toBeGreaterThanOrEqual(
        b.avg_latency_ms as number,
      );
    }
  }

  // The same rule on what the page shows for the newest bucket.
  await page.goto("/operations");
  const readouts = page.locator("#activity-heading + dl");
  await expect(readouts).not.toContainText("no data");
  const values = await readouts.locator("dd.tabular-metric").allInnerTexts();
  const [, avg, p95] = values.map((v) => Number(v.replace(/[^\d.]/g, "")));
  expect(avg).toBeGreaterThan(0);
  expect(p95).toBeGreaterThanOrEqual(avg);
});
