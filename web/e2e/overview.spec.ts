import { expect, test } from "@playwright/test";

/**
 * /overview -- the operations command center. Real stack required. Checks
 * the nav's active-route state and that real data sections render without
 * console errors, never a specific numeric value (those are real and
 * change as the corpus grows).
 */
test("Overview renders real sections with the active nav state and no console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/overview");

  const overviewLink = page.getByRole("link", { name: "Overview" });
  await expect(overviewLink).toHaveAttribute("aria-current", "page");

  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 }),
  ).toBeVisible();
  const systemStatus = page.getByRole("region", { name: "System status" });
  await expect(systemStatus.getByText("Calibration")).toBeVisible();
  await expect(systemStatus.getByText("Evaluation completion")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Judge-state distribution" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reliability pipeline" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent investigations" }),
  ).toBeVisible();

  // The reliability pipeline's structural labels, independent of counts.
  await expect(page.getByText("Flash evaluation")).toBeVisible();
  await expect(page.getByText("Frontier evaluation")).toBeVisible();

  expect(errors).toEqual([]);
});
