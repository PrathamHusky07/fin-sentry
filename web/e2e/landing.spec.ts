import { expect, test } from "@playwright/test";

/**
 * The presentation layer (/). Needs only the web app: nothing on this page
 * reads the gateway. Deterministic structural assertions: the hero, the
 * interactive system map, the decision ledger, the evidence frames, the
 * truth-boundary copy rules, and the CTAs.
 */
test.describe("Landing page", () => {
  test("renders the hero, the system map, the ledger and the evidence frames", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /Guard every answer/, level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Fin-Sentry in one picture/ }),
    ).toBeVisible();

    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    await expect(map).toBeVisible();
    for (const stage of [
      "Client",
      "Gateway",
      "Input rails",
      "Retrieval",
      "Generation",
      "Output rails",
      "Response",
      "Event stream",
      "Flash judge",
      "Deterministic sampler",
      "Frontier judge",
      "Calibration",
      "RisingWave",
      "Investigations",
      "MCP server",
    ]) {
      await expect(
        map.getByRole("button", { name: new RegExp(`^${stage}\\.`) }),
      ).toBeVisible();
    }

    await expect(
      page.getByRole("heading", { name: /Six decisions/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /real disagreement/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Overview command center/i }),
    ).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("the decision ledger has six rows with the four ledger columns and no known-limits section", async ({
    page,
  }) => {
    await page.goto("/");
    const ledger = page.getByRole("region", { name: /Six decisions/ });
    const rows = ledger.locator("ol > li");
    await expect(rows).toHaveCount(6);
    for (const column of ["Problem", "Decision", "Tradeoff", "Consequence"]) {
      await expect(rows.first()).toContainText(column);
    }
    await expect(page.getByText(/Known limits/i)).toHaveCount(0);
    await expect(page.getByText(/does not do yet/i)).toHaveCount(0);
  });

  test("hovering a station brightens it and fills the caption strip", async ({
    page,
  }) => {
    await page.goto("/");
    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    const sampler = map.getByRole("button", {
      name: /^Deterministic sampler\./,
    });
    await sampler.hover();
    const detail = page.locator("#topology-detail");
    await expect(detail).toContainText("Deterministic sampler");
    await expect(detail).toContainText(/trace id/i);
    await expect(detail).toContainText("Why it exists");
    // The active station grows; a station far from it recedes.
    const grown = await sampler
      .locator("circle")
      .nth(1)
      .evaluate((el) => getComputedStyle(el).transform);
    expect(grown).not.toBe("none");
    const unrelated = map.getByRole("button", { name: /^MCP server\./ });
    await expect
      .poll(async () =>
        Number(await unrelated.evaluate((el) => getComputedStyle(el).opacity)),
      )
      .toBeLessThan(0.5);
  });

  test("calibration is drawn as measuring the frontier judge, in the arrow's direction", async ({
    page,
  }) => {
    await page.goto("/");
    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    const label = map.getByText("measured by", { exact: true });
    await expect(label).toBeVisible();
    const frontier = await map
      .getByRole("button", { name: /^Frontier judge\./ })
      .boundingBox();
    const calibration = await map
      .getByRole("button", { name: /^Calibration\./ })
      .boundingBox();
    const labelBox = await label.boundingBox();
    const frontierRight = (frontier?.x ?? 0) + (frontier?.width ?? 0) / 2;
    expect(frontierRight).toBeLessThan(labelBox?.x ?? 0);
    expect((labelBox?.x ?? 0) + (labelBox?.width ?? 0)).toBeLessThan(
      (calibration?.x ?? 0) + (calibration?.width ?? 0),
    );
  });

  test("copy rules: current model names, no dev host, no repo paths, no stale claims", async ({
    page,
  }) => {
    await page.goto("/");
    const body = page.locator("body");
    await expect(body).toContainText("gemini-3.6-flash");
    await expect(body).not.toContainText(/2\.5 Flash/);
    await expect(body).not.toContainText(/weekly/i);
    await expect(body).not.toContainText(/runs locally/i);
    await expect(body).not.toContainText(/localhost|127\.0\.0\.1|:3000|:8000/);
    await expect(body).not.toContainText(/finsentry\/|docs\/adr|\.py\b/);
    await expect(body).not.toContainText(/sha256\(trace id\)/);
    await expect(body).not.toContainText(/POST \/v1/);
    await expect(body).not.toContainText(/Hover or focus a stage/);
  });

  test("the wordmark links to / and the CTA reaches the command center", async ({
    page,
  }) => {
    await page.goto("/overview");
    await page.getByRole("link", { name: "Fin-Sentry" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.getByRole("link", { name: "Open the command center" }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 }),
    ).toBeVisible();
  });
});
