import { expect, test, type Page } from "@playwright/test";

/**
 * Render checks for the honest-state rules in the trace drawer. The detail
 * response is intercepted in the browser so each state is exercised on
 * purpose, because the live corpus has none of them: a partial flash
 * verdict, an error with an unrecognized error_kind and a block with an
 * unrecognized block_reason. The list endpoint and everything else stay
 * real. This tests rendering, not the gateway.
 */
const BASE = {
  found: true,
  endpoint: "/v1/rag/query",
  ticker: "AAPL",
  query: "A crafted rendering check",
  answer: null,
  confidence: null,
  model_used: null,
  citations: [],
  retrieved_chunk_ids: [],
  block_reason: null,
  block_rail: null,
  error_kind: null,
  error_detail: null,
  timestamp_utc: "2026-01-01T00:00:00Z",
  judge_state: "never_evaluated",
  flash: null,
  frontier: { sampled: false, evidence: null, note: "not sampled" },
  risingwave_connected: true,
  note: "",
};

async function openCrafted(page: Page, id: string, overrides: object) {
  await page.route(`**/ops/traces/${id}`, (route) =>
    route.fulfill({
      json: { ...BASE, app_trace_id: id, ...overrides },
    }),
  );
  await page.goto(`/investigations?trace=${id}`);
  const dialog = page.getByRole("dialog", { name: "Trace detail" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("a partial flash verdict is shown as partial, never as blocked", async ({
  page,
}) => {
  const dialog = await openCrafted(page, "crafted-partial", {
    rag_status: "success",
    answer: "A delivered answer.",
    model_used: "model-x",
    judge_state: "partially_evaluated",
    flash: {
      status: "partial",
      timestamp_utc: null,
      faithfulness_score: 0.9,
      faithfulness_status: "complete",
      answer_relevance_score: null,
      answer_relevance_status: "timeout",
      context_relevance_score: null,
      context_relevance_status: "timeout",
    },
  });
  const path = dialog.locator("section[aria-labelledby='trace-path']");
  const flash = path.getByRole("listitem").filter({ hasText: "Flash judge" });
  await expect(flash).toContainText("Partial: some metrics were skipped");
  await expect(flash).toContainText("Partial:");
  await expect(flash).not.toContainText("Blocked");
});

test("an unrecognized error kind is unclassified, never generation", async ({
  page,
}) => {
  const dialog = await openCrafted(page, "crafted-error", {
    rag_status: "error",
    error_kind: "mystery_fault",
  });
  const path = dialog.locator("section[aria-labelledby='trace-path']");
  await expect(
    path.getByRole("listitem").filter({ hasText: "Unknown stage" }),
  ).toContainText("not mapped to a stage");
  await expect(
    path.getByRole("listitem").filter({ hasText: /^Generation/ }),
  ).toContainText("Not determined");
});

test("an unrecognized block reason is unknown, never the output rails", async ({
  page,
}) => {
  const dialog = await openCrafted(page, "crafted-block", {
    rag_status: "blocked",
    block_reason: "brand_new_reason",
  });
  await expect(dialog).toContainText("Stopped at an unclassified stage");
  await expect(dialog).not.toContainText("Stopped by the output rails");
  const path = dialog.locator("section[aria-labelledby='trace-path']");
  await expect(
    path.getByRole("listitem").filter({ hasText: /^Output rails/ }),
  ).toContainText("Not determined");
});
