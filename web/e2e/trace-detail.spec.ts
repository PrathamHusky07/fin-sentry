import { expect, test } from "@playwright/test";
import {
  DISAGREEMENT_IS_LIVE,
  DISAGREEMENT_TRACE_ID as AMAZON_TRACE_ID,
  NO_LIVE_DISAGREEMENT,
} from "./demo-record";

test.use({ viewport: { width: 1440, height: 900 } });

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
  test.skip(!DISAGREEMENT_IS_LIVE, NO_LIVE_DISAGREEMENT);
  const errors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  // Next's <Link> prefetches (_rsc) are aborted when a page unloads in
  // production. They are not data requests, so they are not failures here.
  page.on("requestfailed", (req) => {
    if (!req.url().includes("_rsc=")) failedRequests.push(req.url());
  });

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

  // The returned answer is the dominant block, and it comes after the
  // question and before the judges' verdict in reading order.
  const answerHeading = dialog.getByRole("heading", {
    name: "Answer returned",
  });
  await expect(answerHeading).toBeVisible();
  const answer = dialog.locator("section[aria-labelledby='trace-answer']");
  await expect(answer).toContainText(/\S{3,}/);
  const answerBox = await answer.boundingBox();
  const bannerBox = await banner.boundingBox();
  const questionBox = await dialog
    .locator("section[aria-labelledby='trace-question']")
    .boundingBox();
  expect(questionBox?.y ?? 0).toBeLessThan(answerBox?.y ?? 0);
  // At xl widths the judges sit beside the answer, so both start in the
  // first screenful. Below that they stack under it.
  expect(bannerBox?.y ?? 0).toBeLessThan(900);

  expect(errors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
