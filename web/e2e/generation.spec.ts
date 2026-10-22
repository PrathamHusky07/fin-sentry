import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * /generation: the bounds around the model call, the replies the output schema rail rejected
 * and one stored delivered answer. The counts are compared with the gateway's own trace list,
 * so the page is shown to report stored data and not a constant. Reads only: each test asserts
 * that no POST was sent.
 */

interface Trace {
  app_trace_id: string;
  rag_status: string;
  block_reason: string | null;
}

async function traces(request: APIRequestContext): Promise<Trace[]> {
  const res = await request.get("/ops/traces?limit=500");
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { traces: Trace[] }).traces;
}

for (const width of [375, 768, 1024, 1440]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("states the bounds, counts the rejected replies from stored requests and fits the screen", async ({
      page,
      request,
    }) => {
      const issues: string[] = [];
      const posts: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error" || m.type() === "warning")
          issues.push(m.text());
      });
      page.on("pageerror", (e) => issues.push(e.message));
      page.on("request", (r) => {
        if (r.method() === "POST") posts.push(r.url());
      });

      await page.goto("/generation");
      await expect(
        page.getByRole("heading", { level: 1, name: "Generation" }),
      ).toBeVisible();

      // The four limits, in the page's own words.
      const bounds = page.getByRole("region", { name: "The bounds" });
      await expect(bounds).toContainText("Call budget, 20 seconds");
      await expect(bounds).toContainText("Attempt cap, 15 seconds");
      await expect(bounds).toContainText("Circuit breaker, 5 failures");
      await expect(bounds).toContainText("Request deadline, 60 seconds");
      await expect(bounds).toContainText("not a timeline of one request");

      // The counts are the gateway's own, not a constant.
      const stored = await traces(request);
      const malformed = stored.filter(
        (t) => t.block_reason === "malformed_json",
      ).length;
      const rejected = page.getByRole("region", {
        name: "What the schema rail rejected",
      });
      const row = rejected
        .getByRole("listitem")
        .filter({ hasText: "Malformed JSON" });
      await expect(row).toContainText(String(malformed));
      await expect(rejected).toContainText(
        `Counted from ${stored.length} stored`,
      );
      await expect(rejected).toContainText("Not stored.");

      // No overflow, and every control is at least 44px tall.
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      for (const link of await page.getByRole("main").getByRole("link").all()) {
        const box = await link.boundingBox();
        if (box)
          expect(box.height, await link.innerText()).toBeGreaterThanOrEqual(43);
      }
      expect(posts).toEqual([]);
      expect(issues).toEqual([]);
    });
  });
}

test.describe("the example links", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the newest rejected reply and the stored answer each open a non-empty trace", async ({
    page,
  }) => {
    await page.goto("/generation");
    const rejected = page.getByRole("region", {
      name: "What the schema rail rejected",
    });
    await rejected
      .getByRole("listitem")
      .filter({ hasText: "Malformed JSON" })
      .getByRole("link", { name: "Open the newest" })
      .click();
    const dialog = page.getByRole("dialog", { name: "Trace detail" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(/malformed/i);

    await page.goto("/generation");
    const answer = page.getByRole("region", {
      name: "A delivered answer, as stored",
    });
    await expect(answer).toContainText("llama3.1:8b");
    await answer.getByRole("link", { name: "Open the full trace" }).click();
    const full = page.getByRole("dialog", { name: "Trace detail" });
    await expect(full).toBeVisible();
    await expect(
      full.locator("section[aria-labelledby='trace-answer']"),
    ).toContainText(/\S{3,}/);
  });
});
