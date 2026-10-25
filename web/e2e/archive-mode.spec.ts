import { expect, test, type Page } from "@playwright/test";

/**
 * Archived-evidence mode, run against the production build made by `npm run build:archive` and
 * served by `npm run start:archive` on :3100. That build points its gateway at a closed port, so a
 * page that still tried to reach a gateway would show an unavailable state and fail these checks.
 *
 * Every expected id, count and figure was computed from docs/demo-archive with a separate script.
 * A test passes only when the page shows the real record, never because a route answered 200.
 */

// The page-level line removed in Day 13 Session 2. It stays here so the specs can assert it is gone.
const REMOVED_BANNER =
  "Archived evidence. This is a recorded copy of real runs, not a live system. Every record keeps its original time.";
const READ_ONLY =
  "This site shows archived evidence and is not connected to a live system, so nothing can be started here.";

interface Traffic {
  foreign: string[];
  mutations: string[];
  errors: string[];
}

/** Records every request that leaves this site's origin, every request that is not a read, and
 * every console error or warning. */
function watch(page: Page): Traffic {
  const t: Traffic = { foreign: [], mutations: [], errors: [] };
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.origin !== "http://localhost:3100") t.foreign.push(r.url());
    if (r.method() !== "GET" && r.method() !== "HEAD") {
      t.mutations.push(`${r.method()} ${r.url()}`);
    }
  });
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") t.errors.push(m.text());
  });
  page.on("pageerror", (e) => t.errors.push(e.message));
  return t;
}

function expectQuiet(t: Traffic) {
  expect(t.foreign, "requests that left this site").toEqual([]);
  expect(t.mutations, "requests that are not reads").toEqual([]);
  expect(t.errors, "console errors and warnings").toEqual([]);
}

test.describe("archived-evidence mode", () => {
  test("the landing page shows its capture and carries no archive line", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/");
    const capture = page.locator('img[src*="operations-day12-s8"]');
    // The capture loads lazily, so it is brought into view before its size is read.
    await capture.scrollIntoViewIfNeeded();
    await expect(capture).toBeVisible();
    await expect
      .poll(() => capture.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);
    await expect(page.locator("[data-archive-notice]")).toHaveCount(0);
    await page.goto("/architecture");
    await expect(page.locator("[data-archive-notice]")).toHaveCount(0);
    expectQuiet(t);
  });

  test("no archived page carries the removed page-level archive line", async ({
    page,
  }) => {
    const t = watch(page);
    for (const route of [
      "/overview",
      "/operations",
      "/investigations",
      "/agent",
      "/agent/a771a7e4-3354-4c10-8bb2-d506f1f713e7",
      "/red-team",
      "/generation",
    ]) {
      await page.goto(route);
      await expect(page.locator("[data-archive-notice]"), route).toHaveCount(0);
      await expect(page.locator("body"), route).not.toContainText(
        REMOVED_BANNER,
      );
    }
    expectQuiet(t);
  });

  test("Overview shows the real counts and the stored calibration reading", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/overview");
    const main = page.locator("main");
    await expect(main).toContainText("Derived from 291 persisted executions");
    await expect(main).toContainText(
      "One square is one of 291 persisted executions.",
    );
    await expect(main).toContainText("248");
    await expect(main).toContainText("0.516");
    await expect(main).toContainText(
      "Between the drift and recovery thresholds",
    );
    await expect(main).not.toContainText(
      "The gateway did not return the trace list",
    );
    expectQuiet(t);
  });

  test("Live Operations shows the archived telemetry with its original windows, marked stale", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/operations");
    const faith = page.getByRole("region", {
      name: "Flash judge, faithfulness",
    });
    await expect(faith).toContainText(
      "Latest one-minute bucket, ended Oct 22, 20:00 UTC",
    );
    await expect(faith).toContainText("1.000");
    await expect(faith).toHaveAttribute("data-stale", "true");
    const relevance = page.getByRole("region", {
      name: "Flash judge, relevance",
    });
    await expect(relevance).toContainText("0.560");
    const frontier = page.getByRole("region", {
      name: "Frontier tier, last 15 minutes",
    });
    await expect(frontier).toContainText("Oct 21, 19:37 UTC");
    await expect(frontier).toContainText("Ensemble insufficient");
    await expect(frontier).toContainText("All unavailable");
    await expect(frontier).toHaveAttribute("data-stale", "true");
    await expect(page.locator("main")).toContainText(
      "Newest recorded request Oct 22, 20:00 UTC",
    );
    await expect(page.locator("main")).toContainText("0.516");
    expectQuiet(t);
  });

  test("Live Operations says the gateway probe is not part of the archive", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/operations");
    const probe = page.locator('[data-gateway-probe="unavailable"]');
    await expect(probe).toContainText("not part of the archived evidence");
    await expect(
      page.locator('[data-gateway-health="not-measured"]'),
    ).toContainText("This site has no gateway to time");
    await expect(page.locator('[data-gateway-probe="recorded"]')).toHaveCount(
      0,
    );
    expectQuiet(t);
  });

  test("Investigations lists real executions and filters them through the archive route", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/investigations");
    const rows = page.locator("table tbody tr");
    await expect(rows.first()).toContainText("Oct 22, 20:00:39");
    await expect(rows.first()).toContainText("b357b1c2");

    // The archive route answers the search, and exactly the eight Amazon executions remain.
    const searched = page.waitForResponse(
      (r) =>
        r.url().includes("/api/archive/traces") && r.url().includes("q=amazon"),
    );
    await page.getByPlaceholder("Search query text or trace ID").fill("amazon");
    expect((await searched).status()).toBe(200);
    await expect(rows).toHaveCount(8);
    for (let i = 0; i < 8; i++) {
      await expect(rows.nth(i)).toContainText(/amazon/i);
    }
    expectQuiet(t);
  });

  test("a delivered answer opens with its flash scores and the frontier reasoning", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto(
      "/investigations?trace=8d03c4bf-c4d1-452a-be80-fad342554cdc",
    );
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("8d03c4bf-c4d1-452a-be80-fad342554cdc");
    await expect(dialog).toContainText("Total net sales");
    await expect(dialog).toContainText("gemini-rubric");
    await expect(dialog).toContainText("ensemble_supported");
    await expect(dialog).toContainText("Frontier reasoning, as persisted");
    await expect(dialog).not.toContainText("Trace service unavailable");
    expectQuiet(t);
  });

  test("a frontier refusal opens as the stored record says", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto(
      "/investigations?trace=a0404aca-01ea-4e35-8645-ae1a8f107392",
    );
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("ensemble_refuted");
    await expect(dialog).toContainText("JPM");
    expectQuiet(t);
  });

  test("the Agent lists all seven stored cases and cannot start one", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/agent");
    await expect(page.locator("main")).toContainText("7 stored investigations");
    await expect(page.locator("main")).toContainText(
      "1 is a live execution and 6 are fixture replays",
    );
    const unavailable = page.locator('[data-start-incident="unavailable"]');
    await expect(unavailable).toContainText(READ_ONLY);
    await expect(
      page.getByText("Start an investigation of the live platform"),
    ).toHaveCount(0);
    await expect(
      page.locator('input[name="reference_id"], input[name="ticker"]'),
    ).toHaveCount(0);
    expectQuiet(t);
  });

  test("a stored diagnosis opens with its hypotheses, evidence and timeline", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/agent/43751b14-b080-4f5b-8391-33b914f12f22");
    const main = page.locator("main");
    await expect(main).toContainText("Incident inc-43751b14");
    await expect(main).toContainText("Fixture replay");
    await expect(main).toContainText("The frontier judge has drifted");
    await expect(main).toContainText("Oct 20, 21:53:32 UTC");
    await expect(main).toContainText("3 of 3 predictions met");
    await expect(main).not.toContainText("could not be read");
    expectQuiet(t);
  });

  test("the live case, the failed case and the interrupted case each open honestly", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/agent/a771a7e4-3354-4c10-8bb2-d506f1f713e7");
    await expect(page.locator("main")).toContainText("Live execution");
    await expect(page.locator("main")).toContainText("Oct 20, 22:12:10 UTC");

    await page.goto("/agent/0b3a187f-36c7-4bb8-b230-6e62bad9be54");
    await expect(page.locator("main")).toContainText("FixtureFault");

    await page.goto("/agent/90e8aa78-73c1-4a02-8b03-16cbae8f7b08");
    await expect(page.locator("main")).toContainText(
      "stopped before it finished",
    );
    expectQuiet(t);
  });

  test("an id the archive does not hold says so and shows no case", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/agent/00000000-0000-0000-0000-000000000000");
    const main = page.locator("main");
    await expect(main).toContainText(
      "No investigation is stored under this id.",
    );
    await expect(main).toContainText(
      "The archive holds no case file with this id.",
    );
    await expect(main).not.toContainText("Incident inc-");
    // The one console message is the browser reporting the 404 the page asked for.
    expect(t.errors).toEqual([
      "Failed to load resource: the server responded with a status of 404 (Not Found)",
    ]);
    expect(t.foreign).toEqual([]);
    expect(t.mutations).toEqual([]);
  });

  test("the Red Team shows the real scenarios and results, and runs are off", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/red-team");
    const main = page.locator("main");
    await expect(main).toContainText("10 versioned scenarios");
    await expect(main).toContainText("9 caught, 1 missed.");
    await expect(main).toContainText("GAP-001");
    await expect(main).toContainText("Known gap confirmed");
    await expect(main).toContainText(READ_ONLY);

    await page.locator('button[aria-controls="execute-body"]').click();
    const body = page.locator("#execute-body");
    await expect(body).toContainText(READ_ONLY);
    await expect(
      body.getByRole("button", { name: /^Review run of all deterministic/ }),
    ).toBeDisabled();
    await expect(
      body.getByRole("button", { name: /^Review run of selected/ }),
    ).toBeDisabled();
    await expect(
      body.getByRole("button", {
        name: /Review run of OUT-003 with Gemini judge/,
      }),
    ).toBeDisabled();
    expectQuiet(t);
  });

  test("a stored execution opens with the reason and the evidence it recorded", async ({
    page,
  }) => {
    const t = watch(page);
    await page.goto("/red-team?execution=f9f714ab-becb-49f1-8d3f-42d85d1abbc2");
    const main = page.locator("main");
    await expect(main).toContainText(
      "The reply passed the schema and regulated-phrase rails.",
    );
    await expect(main).toContainText("GAP-001");
    await expect(main).not.toContainText("could not be read");
    expectQuiet(t);
  });

  test("the archive route answers reads and refuses everything else", async ({
    request,
  }) => {
    const run = await request.get(
      "/api/archive/redteam/runs/b30ab043-bb2a-40c2-8fa3-ce89020b4641",
    );
    expect(run.status()).toBe(200);
    const body = (await run.json()) as {
      run: { outcome_counts: Record<string, number> };
      executions: unknown[];
    };
    expect(body.run.outcome_counts).toEqual({ caught: 8, missed: 1 });
    expect(body.executions).toHaveLength(9);

    expect(
      (await request.post("/api/archive/redteam/runs", { data: {} })).status(),
    ).toBe(405);
    expect(
      (
        await request.post("/api/archive/investigations", { data: {} })
      ).status(),
    ).toBe(405);
    expect(
      (await request.get("/api/archive/gateway-probe/latest")).status(),
    ).toBe(404);
    expect((await request.get("/api/archive/traces?limit=abc")).status()).toBe(
      422,
    );
    // The gateway rewrite is off, so the old /ops path reaches nothing.
    expect((await request.get("/ops/traces")).status()).toBe(404);
  });
});
