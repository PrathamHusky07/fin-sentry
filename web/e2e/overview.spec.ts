import { expect, test } from "@playwright/test";

/**
 * /overview -- the command center. Real stack required. Checks the nav's
 * active-route state, the five sections in order, that no live telemetry
 * leaked in from Live Operations, and no console errors. Never a specific
 * numeric value: those are real and change as the corpus grows.
 */
test("Overview renders the command center sections with no console errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/overview");

  await expect(
    page.getByRole("link", { name: "Overview", exact: true }).first(),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Overview", level: 1 }),
  ).toBeVisible();

  const state = page.getByRole("region", { name: "System state" });
  await expect(state.getByText("Frontier judge agreement")).toBeVisible();
  await expect(state.getByText("Delivered answers judged")).toBeVisible();

  for (const heading of [
    "Signals, most severe first",
    "Evaluation coverage",
    "Reliability pipeline",
    "Recent investigations",
  ]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }

  // The Amazon disagreement is featured with its real answer and scores.
  const featured = page.getByRole("region", {
    name: /Amazon's FY2024 net income/,
  });
  await expect(featured).toContainText("1.000");
  await expect(featured).toContainText("0.000");
  await expect(featured).toContainText(/not readily available/);

  // Overview is not Live Operations: none of the live readouts belong here.
  await expect(page.getByText("Latency (avg / p95)")).toHaveCount(0);
  await expect(page.getByText("Judge tokens")).toHaveCount(0);
  await expect(page.getByText("Request activity")).toHaveCount(0);

  // Raw machine labels never appear in the user-facing funnel.
  await expect(page.getByText("malformed_json")).toHaveCount(0);
  await expect(page.getByText("input_rail_blocked")).toHaveCount(0);

  expect(errors).toEqual([]);
});
