import { expect, test } from "@playwright/test";

/**
 * The presentation layer (/) -- real stack required (see
 * playwright.config.ts). Deterministic structural assertions only: the
 * hero copy, the architecture visualization's real stage labels, the
 * real screenshots, and that the nav still reaches the operations tool.
 * Never an LLM-graded "does this look right" check.
 */
test.describe("Landing page", () => {
  test("renders the hero, the architecture visualization, and the real screenshots", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Fin-Sentry", level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByText(/catches unsafe, unsupported, and mis-evaluated/i),
    ).toBeVisible();

    // The real nine-stage architecture, not a marketing illustration.
    const arch = page.getByRole("img", { name: /Fin-Sentry architecture/i });
    await expect(arch).toBeVisible();
    for (const stage of [
      "Request",
      "Input rails",
      "Retrieval",
      "Generation",
      "Output rails",
      "Flash judge",
      "Frontier judge",
      "Calibration",
      "Investigation",
    ]) {
      await expect(arch.getByText(stage, { exact: true })).toBeVisible();
    }

    // Real screenshots of the real application, not placeholders.
    await expect(
      page.getByRole("img", { name: /Overview command center/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Investigations workspace/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /real disagreement/i }),
    ).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("the wordmark links to / and the nav reaches the operations tool", async ({
    page,
  }) => {
    await page.goto("/overview");
    await page.getByRole("link", { name: "Fin-Sentry" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page
      .getByRole("link", { name: "Open the operations console" })
      .click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 }),
    ).toBeVisible();
  });
});
