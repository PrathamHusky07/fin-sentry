import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Red Team console, in a real browser.
 *
 * Two kinds of test live here and they say so:
 *
 * - REAL STACK tests read the live scenario registry and result store through
 *   the gateway, and one starts a real run of OUT-001 (pure Python rails, no
 *   model calls). They need the gateway, dashboard and Postgres running.
 * - RENDERING tests feed the page fixtures that match the API contract, to see
 *   how each of the five outcomes is drawn. An evaluator outage and a harness
 *   failure cannot be produced on demand against the real stack, so these
 *   prove how the page DRAWS them, not that the platform produced them.
 *
 * One worker, no parallelism, by the project's resource-safety rule.
 */

const ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"];

function watch(page: Page) {
  const problems: string[] = [];
  const opsOrigins = new Set<string>();
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => {
    if (r.failure()?.errorText === "net::ERR_ABORTED") return;
    problems.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`);
  });
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/ops/")) opsOrigins.add(url.origin);
  });
  return { problems, opsOrigins };
}

for (const origin of ORIGINS) {
  test(`REAL STACK: the console reads the live registry and stays same-origin from ${origin}`, async ({
    page,
  }) => {
    const w = watch(page);
    await page.goto(`${origin}/red-team`);
    await expect(
      page.getByRole("heading", { name: "Scenario registry" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("checkbox")).toHaveCount(10);
    await expect(page.getByText("Failed to fetch")).toHaveCount(0);
    expect([...w.opsOrigins]).toEqual([origin]);
    expect(w.problems).toEqual([]);
  });
}

test("REAL STACK: selecting a scenario and running it stores a new execution", async ({
  page,
}) => {
  const w = watch(page);
  await page.goto("/red-team");
  await expect(
    page.getByRole("checkbox", { name: "Select OUT-001" }),
  ).toBeVisible({ timeout: 15_000 });
  await page.getByRole("checkbox", { name: "Select OUT-001" }).check();
  await expect(
    page.getByRole("button", { name: "Run selected (1)" }),
  ).toBeEnabled();

  const before = await page
    .getByRole("button", { name: /^Open evidence for OUT-001/ })
    .count();
  await page.getByRole("button", { name: "Run selected (1)" }).click();

  await expect(page.getByRole("heading", { name: "Run finished" })).toBeVisible(
    {
      timeout: 20_000,
    },
  );
  await expect
    .poll(async () =>
      page.getByRole("button", { name: /^Open evidence for OUT-001/ }).count(),
    )
    .toBeGreaterThan(before);

  const first = page
    .getByRole("button", { name: /^Open evidence for OUT-001/ })
    .first();
  await first.click();
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });
  await expect(dialog).toContainText("Schema enforcement");
  await expect(dialog).toContainText("hallucinated_citation");
  await expect(dialog).toContainText("no gateway request");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  expect(w.problems).toEqual([]);
});

test("a judge-assisted scenario asks for confirmation and starts nothing on cancel", async ({
  page,
}) => {
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/ops/redteam/runs")) {
      posts.push(r.url());
    }
  });
  await page.goto("/red-team");
  await page.getByRole("button", { name: "Run with Gemini judge" }).click();
  await expect(
    page.getByRole("button", { name: "Confirm and run" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(
    page.getByRole("button", { name: "Confirm and run" }),
  ).toHaveCount(0);
  expect(posts).toEqual([]);
  await expect(
    page.getByRole("checkbox", { name: /OUT-003 runs alone/ }),
  ).toBeDisabled();
});

// ---------------------------------------------------------------------------
// RENDERING tests: contract-shaped fixtures, see the header comment.
// ---------------------------------------------------------------------------

type Outcome =
  | "caught"
  | "missed"
  | "evaluator_unavailable"
  | "execution_failed"
  | "inconclusive";

function execution(
  id: string,
  outcome: Outcome,
  over: Record<string, unknown> = {},
) {
  return {
    execution_id: `00000000-0000-0000-0000-00000000000${id}`,
    run_id: "11111111-1111-1111-1111-111111111111",
    seq: Number(id),
    scenario_id: "DI-001",
    scenario_version: 1,
    category: "direct_injection",
    target_layer: "prompt-guard-2",
    mode: "deterministic",
    expected: {
      outcome: "caught",
      layer: "prompt-guard-2",
      check: null,
      known_gap: false,
      rationale: "Prompt Guard 2 is the first input rail.",
    },
    state: "finished",
    outcome,
    acting_layer: outcome === "caught" ? "prompt-guard-2" : null,
    acting_check: null,
    expectation:
      outcome === "caught"
        ? "met"
        : outcome === "missed"
          ? "not_met"
          : "not_assessable",
    reason: `Fixture reason for ${outcome}.`,
    evidence: {
      gateway_status: outcome === "missed" ? 200 : 403,
      continued_past_input_rails: outcome === "missed",
    },
    trace_ref: null,
    gemini_calls: 0,
    cost_usd: 0,
    started_at: "2026-10-08T20:00:00Z",
    finished_at: "2026-10-08T20:00:01Z",
    duration_ms: 1000,
    ...over,
  };
}

const ALL_FIVE: Outcome[] = [
  "caught",
  "missed",
  "evaluator_unavailable",
  "execution_failed",
  "inconclusive",
];
const FIXTURE_ROWS = ALL_FIVE.map((o, i) => execution(String(i), o));

async function mockStore(page: Page) {
  const json = (route: Route, body: unknown) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  await page.route("**/ops/redteam/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/scenarios")) {
      return json(route, {
        persistence_available: true,
        scenarios: ALL_FIVE.map((o, i) => ({
          id: `DI-00${i + 1}`,
          version: 1,
          title: `Fixture scenario ${i + 1}`,
          category: "direct_injection",
          target_layer: "prompt-guard-2",
          description: "A fixture.",
          executor: "gateway_route",
          mode: "deterministic",
          expected: FIXTURE_ROWS[i].expected,
          required_evidence: ["gateway_status"],
          severity: "high",
          severity_rationale: "Fixture.",
          input: { query: "fixture" },
          last_execution: FIXTURE_ROWS[i],
        })),
      });
    }
    if (url.pathname.endsWith("/runs")) return json(route, []);
    const detail = url.pathname.match(/\/executions\/([^/]+)$/);
    if (detail) {
      const row = FIXTURE_ROWS.find((r) => r.execution_id === detail[1]);
      return row
        ? json(route, row)
        : route.fulfill({ status: 404, body: "{}" });
    }
    return json(route, { executions: FIXTURE_ROWS, next_offset: null });
  });
}

test("RENDERING: each of the five outcomes is drawn distinctly and only caught reads as a detection", async ({
  page,
}) => {
  await mockStore(page);
  const w = watch(page);
  await page.goto("/red-team");
  const table = page.getByRole("table");
  await expect(table).toBeVisible({ timeout: 15_000 });

  for (const label of [
    "Caught",
    "Missed",
    "Evaluator unavailable",
    "Execution failed",
    "Inconclusive",
  ]) {
    await expect(table.getByText(label, { exact: true })).toHaveCount(1);
  }
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(5);
  // The Expected column legitimately says "Caught by Prompt Guard 2" on every
  // row, so the claim is checked on the Observed cell (the fourth column).
  for (const label of [
    "Evaluator unavailable",
    "Execution failed",
    "Inconclusive",
    "Missed",
  ]) {
    const observed = rows.filter({ hasText: label }).locator("td").nth(3);
    await expect(observed).toHaveText(label);
  }
  await expect(rows.filter({ hasText: "Fixture reason" })).toHaveCount(0);
  await expect(rows.locator("td").nth(3)).toHaveText(
    /^Caught\s*Prompt Guard 2$/,
  );
  await expect(
    page.getByRole("heading", { name: "Latest result per scenario" }),
  ).toBeVisible();
  expect(w.problems).toEqual([]);
});

test("RENDERING: the summary counts come from the stored results and the filters narrow the request", async ({
  page,
}) => {
  await mockStore(page);
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/ops/redteam/executions?")) requests.push(r.url());
  });
  await page.goto("/red-team");
  const counts = page.locator("dl").first();
  await expect(counts).toBeVisible();
  await expect(page.getByText("5 of 5 scenarios have a result.")).toBeVisible();
  for (const label of [
    "Caught",
    "Missed",
    "Evaluator unavailable",
    "Execution failed",
    "Inconclusive",
  ]) {
    const cell = counts
      .locator("div")
      .filter({ has: page.getByText(label, { exact: true }) });
    await expect(cell.locator("dd").first()).toHaveText("1");
  }
  await page.getByLabel("Outcome").selectOption("missed");
  await expect
    .poll(() => requests.some((u) => u.includes("outcome=missed")))
    .toBe(true);
});

test("RENDERING: the evidence drawer never credits a layer when the evaluator was unavailable", async ({
  page,
}) => {
  await mockStore(page);
  await page.goto("/red-team");
  await page
    .getByRole("table")
    .locator("tbody tr")
    .filter({ hasText: "Evaluator unavailable" })
    .getByRole("button")
    .click();
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });
  await expect(dialog).toContainText("None credited");
  await expect(dialog).toContainText("Could not run");
  await expect(dialog).toContainText("deterministic execution");
  await expect(dialog).toContainText(
    "not a measurement of live model behavior",
  );
  await expect(dialog).toContainText(
    "no stored trace was found within the lookup window",
  );
  await expect(dialog.getByText("Caught", { exact: true })).toHaveCount(0);
});

test("RENDERING: a gateway request no input rail stopped says it may have reached Gemini, and a block does not", async ({
  page,
}) => {
  await mockStore(page);
  await page.goto("/red-team");
  const rows = page.getByRole("table").locator("tbody tr");
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });

  await rows.filter({ hasText: "Missed" }).first().getByRole("button").click();
  await expect(dialog).toContainText(
    "The runner made no model call of its own",
  );
  await expect(dialog).toContainText("No input rail stopped this request");
  await expect(dialog).toContainText("Either can call Gemini");
  await expect(dialog).not.toContainText("made no billable model calls");
  await page.keyboard.press("Escape");

  await rows.filter({ hasText: "Caught" }).first().getByRole("button").click();
  await expect(dialog).toContainText(
    "The runner made no model call of its own",
  );
  await expect(dialog).not.toContainText("No input rail stopped this request");
});

test("RENDERING: an unreachable store is shown as unknown, not as zero", async ({
  page,
}) => {
  await page.route("**/ops/redteam/scenarios", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ persistence_available: false, scenarios: [] }),
    }),
  );
  await page.route("**/ops/redteam/runs*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"error":"red team store unavailable"}',
    }),
  );
  await page.route("**/ops/redteam/executions*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"error":"red team store unavailable"}',
    }),
  );
  await page.goto("/red-team");
  await expect(
    page.getByText(/The result store could not be read/),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Unknown").first()).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "red team store unavailable" }),
  ).toBeVisible();
});
