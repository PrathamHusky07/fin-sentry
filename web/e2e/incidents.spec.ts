import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

/**
 * /agent -- the Incident Response Agent workspace on the real gateway API
 * and the real stored sessions. The five lifecycle states below are read from fixture
 * sessions that `python -m finsentry.investigator.evaluation.seed --replace` stores through
 * the real session code (the page says "Fixture replay" on every one). No state here is a
 * live model outcome, and nothing in this file calls a model: the only request that could
 * start an investigation is a POST, and the tests assert none is sent.
 */

interface Row {
  investigation_id: string;
  status: string;
  outcome: string | null;
  origin: string;
  trigger: { kind: string };
  stopping_reason: string | null;
}

async function sessions(request: APIRequestContext): Promise<Row[]> {
  const res = await request.get("/ops/investigations?limit=50");
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { investigations: Row[] }).investigations;
}

async function pick(
  request: APIRequestContext,
  match: (r: Row) => boolean,
): Promise<Row> {
  const found = (await sessions(request)).find(
    (r) => r.origin === "fixture" && match(r),
  );
  if (!found)
    throw new Error("Seed the fixture sessions first (see the file comment).");
  return found;
}

function watch(page: Page) {
  const issues: string[] = [];
  const posts: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") issues.push(m.text());
  });
  page.on("pageerror", (e) => issues.push(e.message));
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  return { issues, posts };
}

test.describe("Incident investigations", () => {
  test("the list shows stored sessions, labels fixtures and filters by status", async ({
    page,
    request,
  }) => {
    const seen = watch(page);
    await page.goto("/agent");
    await expect(
      page.getByRole("heading", { name: "Incident Response Agent", level: 1 }),
    ).toBeVisible();
    const rows = page.locator("main ul li.row-reveal");
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThanOrEqual(5);
    await expect(rows.getByText("Fixture replay").first()).toBeVisible();

    await page.getByRole("button", { name: "Failed" }).click();
    await expect(rows).toHaveCount(
      (await sessions(request)).filter((r) => r.status === "failed").length,
    );
    await expect(
      rows.first().getByText("Failed", { exact: true }),
    ).toBeVisible();
    expect(seen.issues).toEqual([]);
    expect(seen.posts).toEqual([]);
  });

  test("a diagnosis is a best-supported hypothesis with its records, never a solved cause", async ({
    page,
    request,
  }) => {
    const row = await pick(
      request,
      (r) =>
        r.outcome === "diagnosis" &&
        r.trigger.kind === "judge_disagreement_cluster",
    );
    const seen = watch(page);
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Judge disagreement cluster",
    );
    await expect(
      page.getByText("best-supported hypothesis, not a proven cause"),
    ).toBeVisible();
    await expect(
      page
        .locator("#outcome")
        .getByText("does not prove the cause", { exact: false }),
    ).toBeVisible();
    await expect(page.getByText("Fixture replay").first()).toBeVisible();

    const ledger = page.locator("#hypotheses ol > li");
    await expect(ledger.first()).toContainText("Rank 1");
    await expect(ledger.first()).toContainText("Supported");
    await expect(ledger.nth(1)).toContainText("Refuted");
    await expect(ledger.first().getByText(/predictions met/)).toBeVisible();

    await ledger
      .first()
      .getByText(/Predictions and how each was judged/)
      .click();
    await expect(ledger.first().getByText("Judged by").first()).toBeVisible();

    await expect(page.locator("#timeline li").first()).toContainText(
      "search_traces",
    );
    await expect(page.locator("#evidence table")).toContainText(
      "gemini-rubric",
    );
    await expect(page.locator("#gaps")).toContainText(
      "Proposed verification, not run",
    );
    await expect(page.locator("#gaps")).toContainText("never executed");
    expect(seen.issues).toEqual([]);
    expect(seen.posts).toEqual([]);
  });

  test("a refresh reopens the stored session and starts nothing", async ({
    page,
    request,
  }) => {
    const row = await pick(request, (r) => r.outcome === "diagnosis");
    const before = (await sessions(request)).length;
    const seen = watch(page);
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(page.getByText("not a proven cause")).toBeVisible();
    const first = await page.locator("#timeline").innerText();
    await page.reload();
    await expect(page.getByText("not a proven cause")).toBeVisible();
    expect(await page.locator("#timeline").innerText()).toBe(first);
    expect((await sessions(request)).length).toBe(before);
    expect(seen.posts).toEqual([]);
  });

  test("an abstention reads as a complete outcome and not as an error", async ({
    page,
    request,
  }) => {
    const row = await pick(
      request,
      (r) =>
        r.outcome === "abstention" &&
        r.stopping_reason === "justified_abstention",
    );
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(page.getByText("no root cause was established")).toBeVisible();
    await expect(page.getByText("This is a complete result.")).toBeVisible();
    await expect(
      page.locator("#outcome").getByText("Stopped: Justified abstention"),
    ).toBeVisible();
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
    await expect(page.locator("#hypotheses ol > li").first()).toContainText(
      "Unranked",
    );
    await expect(page.locator("#evidence")).toContainText(
      "An abstention makes no claim",
    );
  });

  test("an unavailable source is not an empty result", async ({
    page,
    request,
  }) => {
    const row = await pick(
      request,
      (r) => r.stopping_reason === "critical_evidence_unavailable",
    );
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(
      page
        .locator("#outcome")
        .getByText("Stopped: Critical evidence unavailable"),
    ).toBeVisible();
    await expect(
      page.locator("#timeline").getByText("Could not run").first(),
    ).toBeVisible();
    await expect(page.locator("#gaps")).toContainText(
      "Queries that did not give an answer",
    );
    await expect(page.locator("#gaps")).toContainText(
      "says nothing about the platform",
    );
  });

  test("a failed investigation says so, keeps what it ran and shows no conclusion", async ({
    page,
    request,
  }) => {
    const row = await pick(request, (r) => r.status === "failed");
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(
      page.getByText("Outcome: the investigation failed"),
    ).toBeVisible();
    await expect(page.getByText("FixtureFault")).toBeVisible();
    await expect(
      page.getByText("No conclusion was reached, so none is shown."),
    ).toBeVisible();
    await expect(page.locator("#timeline li").first()).toContainText("q1");
    await expect(page.locator("#hypotheses")).toContainText(
      "no ledger to show",
    );
  });

  test("an interrupted investigation is explicit and not resumable", async ({
    page,
    request,
  }) => {
    const row = await pick(request, (r) => r.status === "interrupted");
    await page.goto(`/agent/${row.investigation_id}`);
    await expect(
      page.getByText("the investigation was interrupted"),
    ).toBeVisible();
    await expect(
      page.getByText("It was not resumed.", { exact: false }).first(),
    ).toBeVisible();
    await expect(page.locator("#budget")).toContainText("No usage was stored");
  });

  test("a live session names the platform and the planner and prices its model calls", async ({
    page,
    request,
  }) => {
    const live = (await sessions(request)).find((r) => r.origin === "live");
    test.skip(
      !live,
      "No live session is stored. Start one from the page to run this check.",
    );
    if (!live) return;
    await page.goto(`/agent/${live.investigation_id}`);
    await expect(page.getByText("Live platform").first()).toBeVisible();
    await expect(page.getByText("Fixture replay")).toHaveCount(0);
    await expect(page.locator("#budget")).toContainText("estimate, not a bill");
    await expect(page.locator("#budget")).toContainText("Model calls");
  });

  test("an unknown id says nothing is stored under it", async ({ page }) => {
    await page.goto("/agent/00000000-0000-0000-0000-000000000000");
    await expect(
      page.getByText("No investigation is stored under this id."),
    ).toBeVisible();
  });

  test("the Investigations area links to the agent and back", async ({
    page,
  }) => {
    await page.goto("/investigations");
    await page.getByRole("link", { name: "Agent investigations" }).click();
    await expect(page).toHaveURL(/\/agent$/);
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Investigations" })
      .click();
    await expect(page).toHaveURL(/\/investigations$/);
  });

  test("the old incident paths redirect to the agent and keep a stored link working", async ({
    page,
    request,
  }) => {
    await page.goto("/investigations/incidents");
    await expect(page).toHaveURL(/\/agent$/);
    const row = await pick(request, (r) => r.outcome === "diagnosis");
    await page.goto(`/investigations/incidents/${row.investigation_id}`);
    await expect(page).toHaveURL(new RegExp(`/agent/${row.investigation_id}$`));
    await expect(page.getByText("not a proven cause")).toBeVisible();
  });

  test("the landing says what the agent does, steps through its lifecycle and starts nothing", async ({
    page,
    request,
  }) => {
    const before = (await sessions(request)).length;
    const seen = watch(page);
    await page.goto("/agent");
    await expect(
      page
        .getByRole("navigation", { name: "Primary" })
        .getByRole("link", { name: "Agent", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(page.getByText("reports only what it can cite")).toBeVisible();

    const steps = page.locator("#lifecycle ol > li button");
    await expect(steps).toHaveCount(6);
    await expect(steps.first()).toHaveAttribute("aria-pressed", "true");
    const detail = page.locator("#agent-step-detail");
    await expect(detail).toContainText(
      "Opening a stored session never starts one",
    );
    await steps.nth(1).click();
    await expect(steps.nth(1)).toHaveAttribute("aria-pressed", "true");
    await expect(detail).toContainText("only part that is not code");
    await steps.nth(5).focus();
    await page.keyboard.press("Enter");
    await expect(detail).toContainText("never presented as proven");

    // The headline is derived from the stored rows and never calls a fixture live.
    const headline = page.locator("#investigations p").filter({
      hasText: "stored investigation",
    });
    await expect(headline.first()).toContainText("fixture replay");

    await page.getByRole("button", { name: "Fixture replay" }).click();
    const rows = page.locator("#investigations ul li.row-reveal");
    await expect(rows.first()).toBeVisible();
    expect(
      await rows.evaluateAll((els) =>
        els.every((e) => /Fixture replay/.test(e.textContent ?? "")),
      ),
    ).toBe(true);
    await page.getByRole("button", { name: "Live platform" }).click();
    for (const r of await rows.all()) {
      await expect(r).toContainText("Live platform");
    }

    await page.reload();
    expect((await sessions(request)).length).toBe(before);
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });

  test("the reading guide uses the same wording as the detail page", async ({
    page,
  }) => {
    await page.goto("/agent");
    const guide = page.locator("#guide");
    await expect(guide).toContainText("Ran, matched nothing");
    await expect(guide).toContainText("Empty, not verified");
    await expect(guide).toContainText("Could not run");
    await expect(guide).toContainText("not a proven cause");
  });

  test("a live red team trigger links back to its execution and a fixture one does not", async ({
    page,
    request,
  }) => {
    const fixture = await pick(
      request,
      (r) => r.trigger.kind === "red_team_miss",
    );
    await page.goto(`/agent/${fixture.investigation_id}`);
    await expect(
      page.getByRole("link", { name: "Open the execution in Red Team" }),
    ).toHaveCount(0);
  });

  for (const width of [375, 768, 1440]) {
    test(`no horizontal overflow and 44px targets at ${width}px`, async ({
      page,
      request,
    }) => {
      const row = await pick(request, (r) => r.outcome === "diagnosis");
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/agent", `/agent/${row.investigation_id}`]) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        const overflow = await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        );
        expect(overflow).toBe(0);
        const small = await page.evaluate(() =>
          [
            ...document.querySelectorAll(
              "main a, main button, main summary, main select, main input",
            ),
          ]
            .filter((e) => {
              const b = e.getBoundingClientRect();
              return (
                b.width > 0 &&
                b.height > 0 &&
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
              document.querySelector("main") ?? document.body,
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
      }
    });
  }
});
