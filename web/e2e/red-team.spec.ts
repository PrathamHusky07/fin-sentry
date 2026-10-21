import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type Route,
} from "@playwright/test";

/**
 * Red Team console, in a real browser.
 *
 * Three kinds of test live here and each says so:
 *
 * - REAL STACK tests read the live scenario registry and result store through the gateway.
 *   One starts a real run of OUT-001 (pure Python rails, no model calls). They need the
 *   gateway, dashboard and Postgres running.
 * - RENDERING tests feed the page fixtures that match the API contract, to see how each of
 *   the five outcomes, a regression and an outage are drawn. An evaluator outage and a
 *   harness failure cannot be produced on demand against the real stack, so these prove how
 *   the page DRAWS them and not that the platform produced them.
 * - INVESTIGATE tests intercept the one POST that would call a model, so the wiring from a
 *   missed execution to the Agent is proven with no model call and no spend.
 *
 * One worker, no parallelism, by the project's resource-safety rule.
 */

const ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"];

function watch(page: Page) {
  const problems: string[] = [];
  const opsOrigins = new Set<string>();
  const posts: string[] = [];
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
    if (r.method() === "POST") posts.push(r.url());
  });
  return { problems, opsOrigins, posts };
}

const desktop = { width: 1440, height: 900 };

// ---------------------------------------------------------------------------
// REAL STACK
// ---------------------------------------------------------------------------

for (const origin of ORIGINS) {
  test(`REAL STACK: the console reads the live registry and stays same-origin from ${origin}`, async ({
    page,
  }) => {
    await page.setViewportSize(desktop);
    const w = watch(page);
    await page.goto(`${origin}/red-team`);
    await expect(
      page.getByRole("heading", { name: "Defenses and their scenarios" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("[data-scenario]")).toHaveCount(10);
    await expect(page.getByText("Failed to fetch")).toHaveCount(0);
    expect([...w.opsOrigins]).toEqual([origin]);
    expect(w.problems).toEqual([]);
    expect(w.posts).toEqual([]);
  });
}

test("REAL STACK: the known gap leads the page and the five outcomes are all keyed", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  const attention = page.locator("#attention");
  await expect(attention).toContainText("1 known gap remains open", {
    timeout: 15_000,
  });
  const card = attention.getByRole("list", {
    name: "Scenarios that need attention",
  });
  await expect(card).toContainText("Known gap, still missed");
  await expect(card).toContainText("GAP-001");
  await expect(card).toContainText("Expected, stored with the scenario");
  await expect(card).toContainText("Observed, from the latest execution");
  await expect(card).toContainText("Known gap confirmed");
  // The finding is above the key. The key lists all five states and does not draw a zero.
  const keyed = attention.locator("[data-outcome]");
  await expect(keyed).toHaveCount(5);
  await expect(attention.locator('[data-recorded="false"]')).toHaveCount(3);
  await expect(attention.locator('[data-outcome="caught"]')).toContainText(
    "scenarios",
  );
  await expect(
    attention.locator('[data-outcome="evaluator_unavailable"]'),
  ).toContainText("None recorded");
  const above = await attention.evaluate((el) => {
    const finding = el.querySelector("ul[aria-label]")?.getBoundingClientRect();
    const key = el.querySelector("[data-outcome]")?.getBoundingClientRect();
    return (finding?.top ?? 1e9) < (key?.top ?? 0);
  });
  expect(above).toBe(true);
});

test("REAL STACK: scenarios are lanes along the request path and a wide screen opens the finding", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  await expect(page.locator("[data-scenario]").first()).toBeVisible({
    timeout: 15_000,
  });
  const lanes = await page.locator("#defenses section h3").allInnerTexts();
  expect(lanes.map((l) => l.replace(/\s+/g, " ").trim())).toEqual([
    "Prompt Guard 2 Input rails",
    "Llama Guard 3 Input rails",
    "PII redaction Input rails",
    "Retrieval rail Retrieval",
    "Schema enforcement Output rails",
    "Regulated phrases Output rails",
    "Faithfulness Output rails",
  ]);
  const detail = page.getByRole("article", { name: /GAP-001/ });
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("Latest result");
  await expect(detail).toContainText("None credited");
  // The result and the definition are separate tabs.
  await expect(
    detail.getByRole("tab", { name: /Recorded executions/ }),
  ).toHaveAttribute("aria-selected", "true");
  await detail.getByRole("tab", { name: "Definition" }).click();
  await expect(detail).toContainText("It is not a result");
  await expect(detail).toContainText(
    "Controlled input, stored with the scenario",
  );
});

test("REAL STACK: selecting a scenario is kept in the URL and reopens after a reload", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  await page
    .locator('[data-scenario="DI-001"] button[aria-expanded]')
    .click({ timeout: 15_000 });
  await expect(page).toHaveURL(/scenario=DI-001/);
  await expect(page.getByRole("article", { name: /DI-001/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("article", { name: /DI-001/ })).toBeVisible({
    timeout: 15_000,
  });
});

test("REAL STACK: the scenario filters narrow the lanes, live in the URL and survive a reload", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  await expect(page.locator("[data-scenario]")).toHaveCount(10, {
    timeout: 15_000,
  });
  await page
    .getByRole("combobox", { name: "Severity" })
    .selectOption("critical");
  await expect(page).toHaveURL(/severity=critical/);
  await expect(page.getByText("Showing 2 of 10 scenarios.")).toBeVisible();
  await expect(page.locator("[data-scenario]")).toHaveCount(2);
  await page.reload();
  await expect(page.getByText("Showing 2 of 10 scenarios.")).toBeVisible({
    timeout: 15_000,
  });
  await page
    .getByRole("combobox", { name: "Latest result" })
    .selectOption("missed");
  await expect(page.locator("[data-scenario]")).toHaveCount(0);
  await expect(
    page.getByText("No scenario matches these filters."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(page.locator("[data-scenario]")).toHaveCount(10);
  await expect(page).not.toHaveURL(/severity=/);
});

test("REAL STACK: the detail follows the filtered set, and clearing the filters brings the scenario back", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team?severity=critical");
  const rows = page.locator("[data-scenario]");
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });
  const critical = await rows.evaluateAll((els) =>
    els.map((el) => el.getAttribute("data-scenario") ?? ""),
  );
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(rows).toHaveCount(10);
  const ids = await rows.evaluateAll((els) =>
    els.map((el) => el.getAttribute("data-scenario") ?? ""),
  );
  const target = ids.find((id) => !critical.includes(id));
  if (!target)
    throw new Error("every scenario is critical, nothing to filter out");

  await page
    .locator(`[data-scenario="${target}"] button[aria-expanded]`)
    .click();
  const article = page.getByRole("article", { name: new RegExp(target) });
  await expect(article).toBeVisible();

  await page
    .getByRole("combobox", { name: "Severity" })
    .selectOption("critical");
  await expect(article).toHaveCount(0);
  const hidden = page.locator('[data-detail-state="hidden"]');
  await expect(hidden).toContainText(
    `${target} is hidden by the current filters`,
  );
  await expect(page).toHaveURL(new RegExp(`scenario=${target}`));

  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(hidden).toHaveCount(0);
  await expect(article).toBeVisible();
});

test("REAL STACK: fourteen identical re-runs are one row with a count, and every execution is still reachable", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  const toggle = page.getByRole("button", {
    name: /Show the \d+ executions of OUT-001, version 1/,
  });
  await expect(toggle).toBeVisible({ timeout: 15_000 });
  const label = (await toggle.getAttribute("aria-label")) ?? "";
  const count = Number(/the (\d+) executions/.exec(label)?.[1]);
  expect(count).toBeGreaterThanOrEqual(14);
  const rows = page.locator("#executions table tbody tr");
  const grouped = await rows.count();
  await toggle.click();
  await expect(page.locator("#executions table tbody li")).toHaveCount(count);
  await page.getByRole("button", { name: "Show every execution" }).click();
  expect(await rows.count()).toBeGreaterThan(grouped + count - 3);
  await page.getByRole("button", { name: "Group repeated results" }).click();
  expect(await rows.count()).toBeLessThanOrEqual(grouped + 1);
});

test("REAL STACK: selecting a scenario and running it stores a new execution", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  const w = watch(page);
  await page.goto("/red-team");
  await page
    .getByRole("button", { name: "Select scenarios to run together" })
    .click({ timeout: 15_000 });
  await page.getByRole("checkbox", { name: "Select OUT-001" }).check();
  await expect(
    page.getByRole("button", { name: "Run selected (1)" }),
  ).toBeEnabled();

  const countOf = async () => {
    const label =
      (await page
        .getByRole("button", { name: /executions of OUT-001, version 1/ })
        .getAttribute("aria-label")) ?? "";
    return Number(/the (\d+) executions/.exec(label)?.[1]);
  };
  const before = await countOf();
  await page.getByRole("button", { name: "Run selected (1)" }).click();
  await expect(page.getByRole("heading", { name: "Run finished" })).toBeVisible(
    { timeout: 20_000 },
  );
  await expect.poll(countOf).toBeGreaterThan(before);

  await page
    .getByRole("button", { name: /^Open evidence for OUT-001/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });
  await expect(dialog).toContainText("Schema enforcement");
  await expect(dialog).toContainText("hallucinated_citation");
  await expect(dialog).toContainText("no gateway request");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  expect(w.problems).toEqual([]);
});

test("a judge-assisted scenario asks for confirmation, states its recorded cost and starts nothing on cancel", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/ops/redteam/runs")) {
      posts.push(r.url());
    }
  });
  await page.goto("/red-team");
  await page
    .locator('[data-scenario="OUT-003"] button[aria-expanded]')
    .click({ timeout: 15_000 });
  await page.getByRole("button", { name: "Run with Gemini judge" }).click();
  const confirm = page.getByRole("button", { name: "Confirm and run" });
  await expect(confirm).toBeVisible();
  await expect(page.locator("#defenses")).toContainText(
    "The latest stored run made",
  );
  await expect(page.locator("#defenses")).toContainText("recorded $");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);
  expect(posts).toEqual([]);
  // In select mode a judge-assisted scenario cannot be selected, and says why.
  await page
    .getByRole("button", { name: "Select scenarios to run together" })
    .click();
  await expect(
    page.getByRole("checkbox", { name: /OUT-003 runs alone/ }),
  ).toBeDisabled();
});

test("a narrow screen opens a scenario under its row and keeps every target at 44px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/red-team");
  const row = page.locator('[data-scenario="PII-001"]');
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("article")).toHaveCount(0);
  const rowButton = row.getByRole("button", { name: /^PII-001, version/ });
  await rowButton.click();
  const detail = row.getByRole("article", { name: /PII-001/ });
  await expect(detail).toBeVisible();
  await detail.getByRole("button", { name: /Show all 2/ }).count();
  await expect(detail).toContainText("Differed before, matches now");
  await expect(rowButton).toHaveAttribute("aria-expanded", "true");
  await rowButton.click();
  await expect(detail).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// INVESTIGATE: the wiring from a missed execution to the Agent, without a model call.
// ---------------------------------------------------------------------------

async function knownGapExecution(request: APIRequestContext): Promise<string> {
  const res = await request.get("/ops/redteam/scenarios");
  const body = (await res.json()) as {
    scenarios: {
      id: string;
      last_execution: { execution_id: string } | null;
    }[];
  };
  const gap = body.scenarios.find((s) => s.id === "GAP-001");
  if (!gap?.last_execution) throw new Error("GAP-001 has no stored execution");
  return gap.last_execution.execution_id;
}

test("INVESTIGATE: Investigate this asks first, then posts a red_team_miss start and lands on the Agent", async ({
  page,
  request,
}) => {
  await page.setViewportSize(desktop);
  const executionId = await knownGapExecution(request);
  const list = await request.get("/ops/investigations?limit=50");
  const fixture = (
    (await list.json()) as {
      investigations: { investigation_id: string; origin: string }[];
    }
  ).investigations.find((s) => s.origin === "fixture");
  if (!fixture) throw new Error("Seed the fixture sessions first.");
  const posted: unknown[] = [];
  await page.route("**/ops/investigations", async (route: Route) => {
    if (route.request().method() !== "POST") return route.continue();
    posted.push(route.request().postDataJSON());
    const real = await request.get(
      `/ops/investigations/${fixture.investigation_id}`,
    );
    const { timeline, state, report, usage, heartbeat_at, ...summary } =
      (await real.json()) as Record<string, unknown>;
    void timeline;
    void state;
    void report;
    void usage;
    void heartbeat_at;
    return route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ investigation: summary, created: true }),
    });
  });

  const w = watch(page);
  await page.goto("/red-team");
  const card = page
    .getByRole("list", { name: "Scenarios that need attention" })
    .getByRole("listitem")
    .first();
  await expect(card).toContainText("GAP-001", { timeout: 15_000 });
  // Loading, refreshing and hovering post nothing.
  await page.reload();
  await expect(card).toContainText("GAP-001", { timeout: 15_000 });
  expect(posted).toEqual([]);

  await card.getByRole("button", { name: "Investigate this" }).click();
  const group = page.getByRole("group", {
    name: "Confirm starting an investigation",
  });
  await expect(group).toContainText("nine read-only tools");
  await expect(group).toContainText("$0.10 session cap");
  await group.getByRole("button", { name: "Cancel" }).click();
  expect(posted).toEqual([]);

  await card.getByRole("button", { name: "Investigate this" }).click();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/agent/${fixture.investigation_id}$`),
  );
  expect(posted).toEqual([
    { kind: "red_team_miss", reference_id: executionId, window_minutes: 1440 },
  ]);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(w.problems).toEqual([]);
});

test("INVESTIGATE: a stored investigation of the same execution is offered and nothing is started", async ({
  page,
  request,
}) => {
  await page.setViewportSize(desktop);
  const executionId = await knownGapExecution(request);
  await page.route("**/ops/investigations?*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const real = await route.fetch();
    const body = (await real.json()) as {
      investigations: Record<string, unknown>[];
    };
    const base = body.investigations[0];
    body.investigations.unshift({
      ...base,
      investigation_id: "00000000-0000-0000-0000-0000000000aa",
      trigger: {
        kind: "red_team_miss",
        reference_id: executionId,
        description: "Red Team GAP-001",
      },
    });
    return route.fulfill({ response: real, json: body });
  });
  const w = watch(page);
  await page.goto("/red-team");
  const link = page
    .getByRole("list", { name: "Scenarios that need attention" })
    .getByRole("link", { name: /Open the stored investigation/ });
  await expect(link).toBeVisible({ timeout: 15_000 });
  await expect(link).toHaveAttribute(
    "href",
    "/agent/00000000-0000-0000-0000-0000000000aa",
  );
  await expect(
    page
      .getByRole("list", { name: "Scenarios that need attention" })
      .getByRole("button", { name: "Investigate again" }),
  ).toBeVisible();
  expect(w.posts).toEqual([]);
});

test("INVESTIGATE: a refusal from the start route is shown as it was sent and navigates nowhere", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.route("**/ops/investigations", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: '{"error":"no model is configured here, so no investigation can start"}',
        })
      : route.continue(),
  );
  await page.goto("/red-team");
  const card = page
    .getByRole("list", { name: "Scenarios that need attention" })
    .getByRole("listitem")
    .first();
  await card.getByRole("button", { name: "Investigate this" }).click({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(card.getByRole("status")).toContainText(
    "no model is configured",
  );
  await expect(page).toHaveURL(/\/red-team/);
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
    started_at: `2026-10-08T20:0${id}:00Z`,
    finished_at: `2026-10-08T20:0${id}:01Z`,
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

type Row = ReturnType<typeof execution>;

async function mockStore(
  page: Page,
  rows: Row[] = FIXTURE_ROWS,
  scenarioIds?: string[],
) {
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
        scenarios: rows.map((row, i) => ({
          id:
            scenarioIds?.[i] ??
            (row.scenario_id === "DI-001" ? `DI-00${i + 1}` : row.scenario_id),
          version: 1,
          title: `Fixture scenario ${i + 1}`,
          category: "direct_injection",
          target_layer: "prompt-guard-2",
          description: "A fixture.",
          executor: String(row.scenario_id).startsWith("OUT")
            ? "output_rails"
            : "gateway_route",
          mode: "deterministic",
          expected: row.expected,
          required_evidence: ["gateway_status"],
          severity: "high",
          severity_rationale: "Fixture.",
          input: { query: "fixture" },
          last_execution: row,
        })),
      });
    }
    if (url.pathname.endsWith("/runs")) return json(route, []);
    const detail = url.pathname.match(/\/executions\/([^/]+)$/);
    if (detail) {
      const row = rows.find((r) => r.execution_id === detail[1]);
      return row
        ? json(route, row)
        : route.fulfill({ status: 404, body: "{}" });
    }
    return json(route, { executions: rows, next_offset: null });
  });
}

const logRows = (page: Page) => page.locator("#executions table tbody tr");
/** A log row by what its Observed cell says. The Expected cell says "Caught by Prompt Guard 2"
 * on every row of these fixtures, so a text filter on the whole row cannot tell them apart. */
const observedRow = (page: Page, label: string) =>
  logRows(page).filter({
    has: page.locator("td:nth-child(4)", { hasText: label }),
  });

test("RENDERING: each of the five outcomes is drawn distinctly and only caught reads as a detection", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await mockStore(page);
  const w = watch(page);
  await page.goto("/red-team");
  const table = page.locator("#executions table");
  await expect(table).toBeVisible({ timeout: 15_000 });

  const rows = logRows(page);
  await expect(rows).toHaveCount(5);
  for (const label of [
    "Evaluator unavailable",
    "Execution failed",
    "Inconclusive",
    "Missed",
  ]) {
    const observed = rows.filter({ hasText: label }).locator("td").nth(3);
    await expect(observed.getByText(label, { exact: true })).toHaveCount(1);
    await expect(observed).not.toContainText("Caught");
  }
  await expect(observedRow(page, "Caught").locator("td").nth(3)).toContainText(
    "Prompt Guard 2",
  );
  await expect(rows.filter({ hasText: "Fixture reason" })).toHaveCount(0);

  // The key draws a distinct glyph shape per outcome, so no state depends on color alone.
  const shapes = await page
    .locator("#attention [data-outcome] dt svg")
    .evaluateAll((svgs) => svgs.map((s) => s.innerHTML));
  expect(new Set(shapes).size).toBe(5);
  // Only the missed result is a miss. A dashed border is never a detection.
  await expect(
    page.locator('#attention [data-outcome="caught"]'),
  ).toContainText("1 scenario");
  expect(w.problems).toEqual([]);
});

test("RENDERING: the counts come from the stored results and the filters narrow the loaded executions", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await mockStore(page);
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/ops/redteam/executions")) requests.push(r.url());
  });
  await page.goto("/red-team");
  await expect(page.locator("#attention")).toContainText(
    "scenario was missed and expected to be caught",
    { timeout: 15_000 },
  );
  for (const outcome of ALL_FIVE) {
    await expect(
      page.locator(`#attention [data-outcome="${outcome}"]`),
    ).toContainText("1 scenario, 1 execution");
  }
  const before = requests.length;
  await page.getByRole("combobox", { name: "Outcome" }).selectOption("missed");
  await expect(logRows(page)).toHaveCount(1);
  // The filter works on what was loaded and asks the API for nothing more.
  expect(requests.length).toBe(before);
  await page.getByRole("button", { name: "Clear filters" }).last().click();
  await expect(logRows(page)).toHaveCount(5);
});

test("RENDERING: a scenario caught before and missed now is called a regression, and a caught result that differs does not read as a match", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  const caught = execution("1", "caught");
  const missed = execution("2", "missed");
  const differs = execution("3", "caught", {
    scenario_id: "PII-001",
    category: "pii",
    target_layer: "pii-redaction",
    expectation: "not_met",
    acting_layer: "llama-guard-3",
    expected: {
      outcome: "caught",
      layer: "pii-redaction",
      check: null,
      known_gap: false,
      rationale: "PII redaction runs first.",
    },
  });
  await mockStore(page, [missed, differs], ["DI-001", "PII-001"]);
  // History for DI-001 needs the earlier caught execution too.
  await page.route("**/ops/redteam/executions?*", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        executions: [differs, missed, caught],
        next_offset: null,
      }),
    }),
  );
  await page.goto("/red-team");
  const list = page.getByRole("list", {
    name: "Scenarios that need attention",
  });
  const items = list.getByRole("listitem");
  await expect(items.first()).toContainText("Caught before, missed now", {
    timeout: 15_000,
  });
  await expect(items.nth(1)).toContainText("Caught, but not as expected");
  await expect(items.nth(1)).toContainText("Differs from expectation");
  await expect(items.nth(1)).toContainText(
    "Expected PII redaction. Llama Guard 3 acted.",
  );
  // The log marks the change that led into the missed row.
  await expect(
    logRows(page).filter({ hasText: "Caught before, missed now" }),
  ).toHaveCount(1);
  // And the scenario history says the same.
  await page.locator('[data-scenario="DI-001"] button[aria-expanded]').click();
  await expect(page.getByRole("article", { name: /DI-001/ })).toContainText(
    "Caught before, missed now",
  );
  await expect(
    page.locator('[data-scenario="PII-001"] [class*="warning"]').first(),
  ).toBeVisible();
});

test("RENDERING: the evidence drawer never credits a layer when the evaluator was unavailable", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await mockStore(page);
  await page.goto("/red-team");
  await logRows(page)
    .filter({ hasText: "Evaluator unavailable" })
    .getByRole("button")
    .click({ timeout: 15_000 });
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
  // A result that says nothing about a defense offers no investigation.
  await expect(
    dialog.getByRole("button", { name: "Investigate this" }),
  ).toHaveCount(0);
});

test("RENDERING: a gateway request no input rail stopped says it may have reached Gemini, and a block does not", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await mockStore(page);
  await page.goto("/red-team");
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });

  await logRows(page)
    .filter({ hasText: "Missed" })
    .first()
    .getByRole("button")
    .click({ timeout: 15_000 });
  await expect(dialog).toContainText(
    "The runner made no model call of its own",
  );
  await expect(dialog).toContainText("No input rail stopped this request");
  await expect(dialog).toContainText("Either can call Gemini");
  await expect(dialog).not.toContainText("made no billable model calls");
  // A miss offers an investigation, from the drawer as well.
  await expect(
    dialog.getByRole("button", { name: "Investigate this" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");

  await observedRow(page, "Caught").first().getByRole("button").click();
  await expect(dialog).toContainText(
    "The runner made no model call of its own",
  );
  await expect(dialog).not.toContainText("No input rail stopped this request");
});

test("RENDERING: an unreachable store is shown as unknown, not as zero", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.route("**/ops/redteam/scenarios", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ persistence_available: false, scenarios: [] }),
    }),
  );
  for (const pattern of [
    "**/ops/redteam/runs*",
    "**/ops/redteam/executions*",
  ]) {
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"error":"red team store unavailable"}',
      }),
    );
  }
  await page.goto("/red-team");
  await expect(
    page.getByText(/The result store could not be read/),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    page.locator("#attention [data-outcome]").getByText("Unknown").first(),
  ).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "red team store unavailable" }),
  ).toBeVisible();
});

test("RENDERING: an interrupted gateway execution says it was interrupted and that a send is unknown, never that it did not continue", async ({
  page,
}) => {
  await mockStore(page, [
    execution("1", "execution_failed", {
      reason: "The execution exceeded its 90 second limit.",
      evidence: { continuation_unknown: true },
    }),
  ]);
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  await logRows(page).getByRole("button").first().click({ timeout: 15_000 });
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });
  const continuation = dialog.getByTestId("continuation");
  await expect(continuation).toHaveAttribute("data-state", "unknown");
  await expect(continuation).toContainText("Interrupted, continuation unknown");
  await expect(continuation).toContainText(
    "interrupted before it recorded whether a request was sent or went past the input rails",
  );
  await expect(dialog).not.toContainText("Did not continue");
  await expect(dialog).not.toContainText("No input rail stopped this request");
  await expect(dialog).toContainText(
    "interrupted before a result was recorded. Whether a gateway request was sent is unknown",
  );
  await expect(dialog).not.toContainText("tried to send a gateway request");
  await expect(dialog).not.toContainText("called the defense directly");
  await expect(dialog.getByText("Execution failed").first()).toBeVisible();
  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(continuation).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(
      0,
    );
  }
});

test("RENDERING: a legacy gateway execution with no evidence does not claim a direct call, and one with evidence keeps its provenance", async ({
  page,
}) => {
  await mockStore(page, [
    execution("1", "execution_failed", {
      reason: "The harness raised RuntimeError. See the gateway log.",
      evidence: {},
    }),
    execution("2", "missed"),
  ]);
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });

  await logRows(page)
    .filter({ hasText: "Execution failed" })
    .getByRole("button")
    .first()
    .click({ timeout: 15_000 });
  await expect(dialog).toContainText(
    "Gateway execution provenance not recorded.",
  );
  await expect(dialog).not.toContainText("called the defense directly");
  await expect(dialog).not.toContainText("sent no gateway request");
  await page.keyboard.press("Escape");

  await logRows(page)
    .filter({ hasText: "Missed" })
    .getByRole("button")
    .first()
    .click();
  await expect(dialog).toContainText(
    "sent a gateway request, but no stored trace",
  );
  await expect(dialog).not.toContainText("provenance not recorded");
});

test("RENDERING: a confirmed block reads did not continue and a confirmed pass reads continued", async ({
  page,
}) => {
  await mockStore(page, [execution("1", "caught"), execution("2", "missed")]);
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  const dialog = page.getByRole("dialog", { name: "Execution evidence" });

  await observedRow(page, "Caught")
    .first()
    .getByRole("button")
    .click({ timeout: 15_000 });
  await expect(dialog.getByTestId("continuation")).toHaveAttribute(
    "data-state",
    "stopped",
  );
  await expect(dialog).toContainText("Did not continue");
  await expect(dialog).not.toContainText("continuation unknown");
  await page.keyboard.press("Escape");

  await logRows(page)
    .filter({ hasText: "Missed" })
    .first()
    .getByRole("button")
    .click();
  await expect(dialog.getByTestId("continuation")).toHaveAttribute(
    "data-state",
    "continued",
  );
  await expect(dialog).toContainText(
    "Continued past the input rails (Gemini calls possible)",
  );
});

test("RENDERING: a safety-bound skip reads Not run (safety bound), and a real harness failure still reads as one", async ({
  page,
}) => {
  await mockStore(page, [
    execution("1", "execution_failed", {
      reason: "Not run. An earlier gateway scenario in this run went on.",
      evidence: { skipped_by_safety_bound: true },
      duration_ms: 0,
    }),
    execution("2", "execution_failed", {
      scenario_id: "OUT-001",
      reason: "The harness raised RuntimeError. See the gateway log.",
      evidence: {},
    }),
  ]);
  await page.setViewportSize(desktop);
  await page.goto("/red-team");
  await expect(page.locator("#attention")).toContainText(
    "2 results say nothing about a defense",
    { timeout: 15_000 },
  );
  await expect(page.locator("#attention")).toContainText(
    "1 of the latest results was not run (safety bound)",
  );

  const dialog = page.getByRole("dialog", { name: "Execution evidence" });
  const skipped = logRows(page).filter({ hasText: "DI-001" });
  const failed = logRows(page).filter({ hasText: "OUT-001" });
  await expect(skipped.locator("td").nth(3)).toHaveText(
    "Not run (safety bound)",
  );
  await expect(failed.locator("td").nth(3)).toHaveText("Execution failed");

  await skipped.getByRole("button").first().click();
  await expect(dialog).toContainText("intentionally skipped to bound cost");
  await expect(dialog).toContainText("intentionally not run, to bound cost");
  await expect(dialog).not.toContainText("harness itself failed");
  await expect(dialog).not.toContainText("called the defense directly");
  await expect(dialog).not.toContainText("exercised the real defense");
  await expect(dialog.getByTestId("continuation")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await failed.getByRole("button").first().click();
  await expect(dialog).toContainText("Either the test harness failed");
  await expect(dialog).not.toContainText("intentionally skipped");
  await expect(dialog).toContainText("called the defense directly");
});

// ---------------------------------------------------------------------------
// Responsive and motion
// ---------------------------------------------------------------------------

for (const width of [375, 768, 1440]) {
  test(`REAL STACK: no overflow, no target under 44px and no text under 16px on a phone at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const w = watch(page);
    await page.goto("/red-team");
    await expect(page.locator("[data-scenario]").first()).toBeVisible({
      timeout: 15_000,
    });
    // Open a scenario and its history so the detail is part of the check.
    await page
      .locator('[data-scenario="OUT-001"] button[aria-expanded]')
      .click();
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const small = await page.evaluate(() =>
      [
        ...document.querySelectorAll(
          "main a, main button, main select, main input, a[href], button",
        ),
      ]
        .filter((e) => {
          const b = e.getBoundingClientRect();
          return (
            b.width > 0 &&
            b.height > 0 &&
            !e.closest("svg") &&
            !e.classList.contains("sr-only") &&
            !(e instanceof HTMLInputElement && e.type === "checkbox") &&
            (b.height < 43.5 || b.width < 43.5)
          );
        })
        .map((e) => e.textContent?.trim().slice(0, 30)),
    );
    expect(small).toEqual([]);
    if (width === 375) {
      const tiny = await page.evaluate(() => {
        const out: string[] = [];
        const walker = document.createTreeWalker(
          document.body,
          NodeFilter.SHOW_TEXT,
        );
        while (walker.nextNode()) {
          const n = walker.currentNode;
          const el = n.parentElement;
          if (!el || !n.textContent?.trim() || el.closest("svg")) continue;
          const box = el.getBoundingClientRect();
          if (box.width === 0 || box.height === 0) continue;
          if (parseFloat(getComputedStyle(el).fontSize) < 15.5) {
            out.push(n.textContent.trim().slice(0, 30));
          }
        }
        return out;
      });
      expect(tiny).toEqual([]);
    }
    expect(w.problems).toEqual([]);
  });
}

test("reduced motion removes the detail's entrance animation", async ({
  page,
}) => {
  await page.setViewportSize(desktop);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/red-team");
  const detail = page.getByRole("article").first();
  await expect(detail).toBeVisible({ timeout: 15_000 });
  const wrapper = detail.locator("xpath=..");
  const name = await wrapper.evaluate(
    (el) => getComputedStyle(el).animationName,
  );
  expect(name).toBe("none");
});
