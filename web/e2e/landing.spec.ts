import { expect, test } from "@playwright/test";

/**
 * The presentation layer (/). Real stack required (see
 * playwright.config.ts). Deterministic structural assertions only: the hero,
 * the interactive topology, the engineering decisions, the product evidence
 * frames, and that the CTAs reach the application.
 */
test.describe("Landing page", () => {
  test("renders the hero, the topology, the decisions and the evidence frames", async ({
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

    const topology = page.getByRole("group", {
      name: /Fin-Sentry system topology/,
    });
    await expect(topology).toBeVisible();
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
      "Sampler",
      "Frontier judge",
      "Calibration",
      "RisingWave",
      "Investigations",
      "MCP server",
    ]) {
      await expect(
        topology.getByRole("button", { name: new RegExp(`^${stage}\\.`) }),
      ).toBeVisible();
    }

    await expect(
      page.getByRole("heading", { name: /Seven choices/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /real disagreement/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Overview command center/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Live Operations/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Investigations workspace/i }),
    ).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("hovering a topology stage shows what it does and why it exists", async ({
    page,
  }) => {
    await page.goto("/");
    const topology = page.getByRole("group", {
      name: /Fin-Sentry system topology/,
    });
    await topology.getByRole("button", { name: /^Sampler\./ }).hover();
    const detail = page.locator("#topology-detail");
    await expect(detail).toContainText("Sampler");
    await expect(detail).toContainText(/trace id/i);
    await expect(detail).toContainText("Why it exists");
  });

  test("does not repeat claims the source disproves", async ({ page }) => {
    await page.goto("/");
    const body = page.locator("body");
    await expect(body).not.toContainText(/2\.5 Flash/);
    await expect(body).not.toContainText(/weekly/i);
    await expect(body).not.toContainText(/runs locally/i);
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
