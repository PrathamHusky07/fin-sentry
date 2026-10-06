import { expect, test } from "@playwright/test";

const AMAZON_TRACE_ID = "96bca4b5-f707-4a93-b421-2674032849b5";

/**
 * The showcase trace -- the real, persisted Amazon FY2024 net-income
 * disagreement (see docs/build-log.md and
 * docs/internal/day9-frontend-data-contract.md). Deep-links directly via
 * ?trace=, the same URL shape Overview's Attention Required and the
 * representative-aggregation summary rows use. Asserts the exact real
 * scores and reasoning text, not a loose "something rendered" check.
 */
test("the Amazon disagreement is reachable and renders the real Flash 1.000 vs Frontier 0.000 scores with reasoning", async ({
  page,
}) => {
  const errors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("requestfailed", (req) => failedRequests.push(req.url()));

  await page.goto(`/investigations?trace=${AMAZON_TRACE_ID}`);

  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible();

  const banner = dialog.getByLabel("Flash and frontier disagree");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("1.000");
  await expect(banner).toContainText("0.000");
  await expect(banner).toContainText(
    /retrieved context explicitly contains Amazon's FY2024 net income/i,
  );

  await expect(dialog).toContainText(
    "What is Amazon's FY2024 net income attributable to shareholders",
  );

  expect(errors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
