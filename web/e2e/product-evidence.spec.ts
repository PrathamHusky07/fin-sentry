import { expect, test } from "@playwright/test";
import { RERUN_TRACE_ID } from "./demo-record";

/**
 * The landing page's product evidence. The Amazon disagreement is shown as a historical
 * example, and the frame's own action opens a real trace of the same question asked again, so it
 * never lands on an empty view and never promises a disagreement the trace does not hold. Needs the gateway, because it follows the link and reads the stored record.
 */
test.use({ viewport: { width: 1440, height: 900 } });

test("the first frame is labeled historical and its action opens a non-empty Amazon trace", async ({
  page,
  request,
}) => {
  const issues: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(m.text());
  });
  await page.goto("/");

  const figure = page
    .locator("figure")
    .filter({ hasText: "The disagreement that justifies the second tier." });
  await expect(figure).toContainText("historical example");
  await expect(figure).toContainText("what a second opinion exists to surface");
  // The caption says what the link opens and that it holds no frontier score.
  await expect(figure).toContainText("without a frontier score");
  // No provenance dates and no storage wording in the visitor-facing copy.
  await expect(figure).not.toContainText(/20\d\d-\d\d-\d\d/);
  await expect(figure).not.toContainText(/stored|expired|event log/i);

  // The label says what it opens. It must not promise a disagreement.
  const action = figure.getByRole("link", { name: /Open the Amazon trace/ });
  await expect(figure.getByRole("link", { name: /disagreement/i })).toHaveCount(
    0,
  );
  await expect(
    figure.getByRole("link", { name: /Filter disagreements/ }),
  ).toHaveCount(0);

  // The record exists in the store, with an answer.
  const stored = await request.get(`/ops/traces/${RERUN_TRACE_ID}`);
  const body = (await stored.json()) as {
    found: boolean;
    answer: string | null;
  };
  expect(body.found).toBe(true);
  expect(body.answer).toBeTruthy();

  await figure.scrollIntoViewIfNeeded();
  await figure.hover();
  await action.click();
  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.locator("section[aria-labelledby='trace-answer']"),
  ).toContainText(/\S{3,}/);
  await expect(dialog).toContainText("Amazon");
  expect(issues).toEqual([]);
});
