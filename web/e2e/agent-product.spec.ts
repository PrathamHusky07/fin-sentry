import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

/**
 * /agent as a forensic product: the mechanism map, the case explorer with its summary, the
 * hypothesis comparison, and the three record states. Reads the real gateway and the stored
 * sessions. Nothing here calls a model, and each test asserts that no POST was sent.
 */

interface Row {
  investigation_id: string;
  status: string;
  outcome: string | null;
  origin: string;
  trigger: { kind: string };
}

async function sessions(request: APIRequestContext): Promise<Row[]> {
  const res = await request.get("/ops/investigations?limit=50");
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { investigations: Row[] }).investigations;
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

test.describe("the investigation map, wide", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("selecting a stage brings it forward, lights its connections and quiets the rest", async ({
    page,
  }) => {
    const seen = watch(page);
    await page.goto("/agent");
    const map = page.locator("#lifecycle svg.im");
    await expect(map).toBeVisible();
    const node = (n: string) =>
      map.locator(`[role="button"][aria-label^="${n}"]`);

    // Nothing is previewed at rest: the selected stage is active and the rest are quiet.
    await expect(node("1. Trigger")).toHaveAttribute("data-state", "active");
    await expect(node("6. Conclude")).toHaveAttribute("data-state", "dim");

    await node("4. Assess").click();
    await expect(node("4. Assess")).toHaveAttribute("aria-pressed", "true");
    await expect(node("4. Assess")).toHaveAttribute("data-state", "active");
    await expect(node("3. Execute")).toHaveAttribute("data-state", "related");
    await expect(node("2. Plan")).toHaveAttribute("data-state", "related");
    await expect(node("1. Trigger")).toHaveAttribute("data-state", "dim");
    await expect(map.locator('g.cn-link[data-state="lit"]')).toHaveCount(4);
    await expect(page.locator("#agent-step-detail")).toContainText(
      "plan once more while budget remains",
    );

    // Only the plan is marked as coming from a model.
    await expect(map.getByText("Model proposes")).toHaveCount(1);
    await expect(map.getByText("Code decides")).toHaveCount(4);

    // The panel says it is a mechanism and that case-file placement is stated.
    await expect(page.locator("#lifecycle")).toContainText(
      "not a record of any one investigation",
    );
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });

  test("the keyboard mirrors the pointer: arrows move, Enter commits", async ({
    page,
  }) => {
    await page.goto("/agent");
    const map = page.locator("#lifecycle svg.im");
    const node = (n: string) =>
      map.locator(`[role="button"][aria-label^="${n}"]`);
    await node("1. Trigger").focus();
    await page.keyboard.press("ArrowRight");
    await expect(node("2. Plan")).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(node("3. Execute")).toBeFocused();
    // Focus previews without committing, exactly as hover does.
    await expect(node("1. Trigger")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Enter");
    await expect(node("3. Execute")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#agent-step-detail")).toContainText(
      "nine read-only tools",
    );
    await page.keyboard.press("ArrowLeft");
    await expect(node("2. Plan")).toBeFocused();
  });

  test("hovering or focusing a stage changes the description before any click, and leaving restores the selection", async ({
    page,
  }) => {
    const seen = watch(page);
    await page.goto("/agent");
    const map = page.locator("#lifecycle svg.im");
    const node = (n: string) =>
      map.locator(`[role="button"][aria-label^="${n}"]`);
    const panel = page.locator("#agent-step-detail");
    await expect(panel).toHaveAttribute("aria-label", /^Stage 1: Trigger/);

    // Pointer: standing on a stage shows that stage's description at once. Nothing is clicked.
    await node("2. Plan").hover();
    await expect(panel).toHaveAttribute("aria-label", /^Stage 2: Plan/);
    await expect(panel).toContainText("competing hypotheses");
    await expect(panel).toContainText("Preview. Click or press Enter");
    await expect(node("1. Trigger")).toHaveAttribute("aria-pressed", "true");
    await expect(node("2. Plan")).toHaveAttribute("aria-pressed", "false");
    await node("4. Assess").hover();
    await expect(panel).toHaveAttribute("aria-label", /^Stage 4: Assess/);

    // Leaving restores the committed selection.
    await page.mouse.move(2, 2);
    await expect(panel).toHaveAttribute("aria-label", /^Stage 1: Trigger/);
    await expect(panel).not.toContainText("Preview. Click or press Enter");

    // A click commits, and the commitment survives the pointer leaving.
    await node("2. Plan").click();
    await page.mouse.move(2, 2);
    await expect(panel).toHaveAttribute("aria-label", /^Stage 2: Plan/);
    await expect(node("2. Plan")).toHaveAttribute("aria-pressed", "true");

    // Keyboard focus previews exactly as hover does, and Enter commits.
    await page.keyboard.press("ArrowRight");
    await expect(node("3. Execute")).toBeFocused();
    await expect(panel).toHaveAttribute("aria-label", /^Stage 3: Execute/);
    await expect(node("2. Plan")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("ArrowRight");
    await expect(panel).toHaveAttribute("aria-label", /^Stage 4: Assess/);
    await page.keyboard.press("Enter");
    await expect(node("4. Assess")).toHaveAttribute("aria-pressed", "true");
    await page.mouse.click(2, 2);
    await expect(panel).toHaveAttribute("aria-label", /^Stage 4: Assess/);
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });

  test("reduced motion keeps the state and removes the movement", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/agent");
    const node = page.locator(
      '#lifecycle svg.im [role="button"][aria-label^="2. Plan"]',
    );
    await node.click();
    await expect(node).toHaveAttribute("data-state", "active");
    expect(await node.evaluate((el) => getComputedStyle(el).transform)).toBe(
      "none",
    );
  });
});

test.describe("the investigation map, narrow", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("is a vertical outline whose selected stage opens in place", async ({
    page,
  }) => {
    await page.goto("/agent");
    await expect(page.locator("#lifecycle svg.im")).toHaveCount(0);
    const steps = page.locator("#lifecycle ol > li > button");
    await expect(steps).toHaveCount(6);
    await steps.nth(1).click();
    await expect(steps.nth(1)).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#agent-step-detail")).toHaveCount(1);
    await expect(
      page.locator("#lifecycle ol > li").nth(1).locator("#agent-step-detail"),
    ).toContainText("Nothing the planner writes can later");
  });
});

test.describe("the case explorer", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("selecting a case opens its summary without running anything", async ({
    page,
    request,
  }) => {
    const before = (await sessions(request)).length;
    const seen = watch(page);
    await page.goto("/agent");
    const rows = page.locator("#investigations ul li.row-reveal");
    await expect(rows.first()).toBeVisible();
    const brief = page.locator("#investigations article");
    await expect(brief).toContainText("Open the case file");

    // A failed case shows no conclusion in its summary.
    await rows.filter({ hasText: "The investigator raised an error" }).click();
    await expect(brief).toContainText("No conclusion was reached");
    await expect(
      brief.getByRole("link", { name: /Open the case file/ }),
    ).toHaveAttribute("href", /\/agent\/[0-9a-f-]+$/);

    // A best-supported hypothesis is labelled as not proven.
    await rows.filter({ hasText: "not proven" }).first().click();
    await expect(brief).toContainText("not proven");

    // An abstention reads as a complete result.
    await rows.filter({ hasText: "No root cause established" }).first().click();
    await expect(brief).toContainText("That is a complete result");

    // The status control is the four real states, with counts.
    const group = page.getByRole("group", { name: "Filter by status" });
    await expect(group.getByRole("button")).toHaveCount(4);
    await group.getByRole("button", { name: /^Interrupted/ }).click();
    await expect(rows).toHaveCount(
      (await sessions(request)).filter((r) => r.status === "interrupted")
        .length,
    );
    await expect(brief).toContainText("Stopped before it finished");

    expect((await sessions(request)).length).toBe(before);
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });
});

test.describe("the hypothesis comparison", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("a rival can be opened from the selected hypothesis, and nothing is proven", async ({
    page,
    request,
  }) => {
    const row = (await sessions(request)).find(
      (r) =>
        r.origin === "fixture" &&
        r.outcome === "diagnosis" &&
        r.trigger.kind === "judge_disagreement_cluster",
    );
    if (!row) throw new Error("Seed the fixture sessions first.");
    await page.goto(`/agent/${row.investigation_id}`);
    const list = page.locator("#hypotheses ol > li");
    await expect(list.first()).toHaveAttribute("data-selected", "true");
    await expect(list.nth(1)).not.toHaveAttribute("data-selected", "true");
    // The unselected hypothesis steps back.
    await expect(list.nth(1)).toHaveClass(/opacity-70/);
    await expect(page.locator("#hypotheses")).toContainText(
      "Supported is not proven",
    );

    const rivals = page
      .locator("#hypotheses section")
      .filter({ hasText: "Rival explanations" });
    await rivals.getByRole("button").first().click();
    await expect(list.nth(1)).toHaveAttribute("data-selected", "true");
    await expect(list.first()).not.toHaveAttribute("data-selected", "true");

    // Layer 3 starts with four readings, including the citation check.
    await expect(page.locator("#trail")).toContainText(
      "cited records trace to a query in this session",
    );
    await expect(page.locator("#trail")).toContainText("Budget consumed");
    await expect(page.locator("#trail")).toContainText(
      "scripted planner calls",
    );
  });
});

test.describe("the three record states", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the border style keeps its meaning, the three read as one balanced set and holding one quiets the rest", async ({
    page,
  }) => {
    await page.goto("/agent");
    const card = (state: string) =>
      page.locator(`#records [data-record-state="${state}"]`);
    // Solid says something about the platform now. Dashed says nothing about it.
    await expect(card("live")).toHaveCSS("border-top-style", "solid");
    for (const state of ["fixture", "historical"]) {
      await expect(card(state)).toHaveCSS("border-top-style", "dashed");
    }
    await expect(card("live")).toContainText(
      "Says something about the platform",
    );
    await expect(card("historical")).toContainText(
      "Says nothing about the platform now",
    );

    // Pointing at one brings it forward and lets the others recede. The border style stays.
    await card("fixture").scrollIntoViewIfNeeded();
    await card("fixture").hover();
    await expect(card("live")).toHaveCSS("opacity", "0.7");
    await expect(card("historical")).toHaveCSS("opacity", "0.7");
    await expect(card("fixture")).toHaveCSS("opacity", "1");
    await expect(card("fixture")).toHaveCSS("border-top-style", "dashed");
    await page.mouse.move(5, 5);
    await expect(card("live")).toHaveCSS("opacity", "1");

    // Keyboard focus does the same without a pointer.
    await card("historical").getByRole("link").focus();
    await expect(card("live")).toHaveCSS("opacity", "0.7");
    await expect(card("historical")).toHaveCSS("opacity", "1");
    await expect(card("historical").locator(".rec-rail")).toHaveCSS(
      "transform",
      "matrix(1, 0, 0, 1, 0, 0)",
    );
  });

  for (const width of [1024, 1440]) {
    test(`at ${width}px the three cards are equal columns of one rendered height with aligned actions`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/agent");
      const cards = page.locator("#records [data-record-state]");
      await expect(cards).toHaveCount(3);
      const boxes = await cards.evaluateAll((els) =>
        els.map((e) => {
          const r = e.getBoundingClientRect();
          const link = e.querySelector("a")?.getBoundingClientRect();
          return {
            top: r.top,
            width: r.width,
            height: r.height,
            actionBottom: link ? link.bottom : null,
          };
        }),
      );
      // One row: the same top edge, so there is no orphan or empty fourth column.
      expect(
        Math.max(...boxes.map((b) => b.top)) -
          Math.min(...boxes.map((b) => b.top)),
      ).toBeLessThan(2);
      // Equal columns and one rendered height, to within a pixel and a half.
      const widths = boxes.map((b) => b.width);
      const heights = boxes.map((b) => b.height);
      expect(Math.max(...widths) - Math.min(...widths)).toBeLessThan(1.5);
      expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1.5);
      // The one action sits on the same line in every card.
      const actions = boxes.map((b) => b.actionBottom);
      expect(actions.every((a) => a !== null)).toBe(true);
      const ys = actions as number[];
      expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(1.5);
    });
  }

  test("under reduced motion the cards do not move or grow", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/agent");
    const fixture = page.locator('#records [data-record-state="fixture"]');
    await fixture.scrollIntoViewIfNeeded();
    await fixture.hover();
    await expect(fixture).toHaveCSS("transform", "none");
  });

  test("each is distinct and the preserved Amazon capture states its scores", async ({
    page,
  }) => {
    const seen = watch(page);
    await page.goto("/agent");
    const states = page.locator("#records [data-record-state]");
    await expect(states).toHaveCount(3);
    await expect(
      states.evaluateAll((els) =>
        els.map((e) => e.getAttribute("data-record-state")),
      ),
    ).resolves.toEqual(["live", "fixture", "historical"]);
    await expect(page.locator("#records")).not.toContainText(
      "Unavailable record",
    );

    // The preserved Amazon capture states the two scores and carries no provenance dates.
    const historical = page.locator(
      '#records [data-record-state="historical"]',
    );
    await expect(historical).toContainText("Amazon judge disagreement");
    await expect(historical).toContainText("1.000");
    await expect(historical).toContainText("0.000");
    await expect(page.locator("#records")).not.toContainText(
      /20\d\d-\d\d-\d\d/,
    );
    await expect(page.locator("#records")).not.toContainText(
      /seven-day retention/,
    );
    await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
    expect(seen.posts).toEqual([]);
    expect(seen.issues).toEqual([]);
  });

  test("an unknown case id is an unavailable record with the one action that exists", async ({
    page,
  }) => {
    await page.goto("/agent/00000000-0000-0000-0000-000000000000");
    const state = page.locator('[data-record-state="unavailable"]');
    await expect(state).toContainText("Unavailable record");
    await expect(state).toContainText(
      "No investigation is stored under this id.",
    );
    await expect(
      state.getByRole("link", { name: "See all investigations" }),
    ).toBeVisible();
  });
});

for (const width of [1024, 1440]) {
  test.describe(`the Incident circle at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("holds both of its labels completely inside", async ({ page }) => {
      await page.goto("/agent");
      const group = page.locator("#lifecycle svg.im g.cn-inner").first();
      await expect(group).toBeVisible();
      // The first inner group is the incident: a circle and two text lines. Every corner of
      // each line's box must lie inside the circle, in the SVG's own units.
      const fit = await group.evaluate((g) => {
        const circle = g.querySelector("circle");
        if (!circle) return null;
        const cx = Number(circle.getAttribute("cx"));
        const cy = Number(circle.getAttribute("cy"));
        const r = Number(circle.getAttribute("r"));
        return [...g.querySelectorAll("text")].map((t) => {
          const b = (t as SVGTextElement).getBBox();
          const corners = [
            [b.x, b.y],
            [b.x + b.width, b.y],
            [b.x, b.y + b.height],
            [b.x + b.width, b.y + b.height],
          ];
          const worst = Math.max(
            ...corners.map(([x, y]) => Math.hypot(x - cx, y - cy)),
          );
          return { text: t.textContent, worst, r };
        });
      });
      expect(fit).not.toBeNull();
      expect(fit?.map((f) => f.text)).toEqual(["Incident", "scope and window"]);
      for (const f of fit ?? []) {
        expect(f.worst, `${f.text} reaches the circle edge`).toBeLessThan(f.r);
      }
    });
  });
}

for (const width of [375, 768]) {
  test.describe(`the incident box at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("holds its text and the page does not overflow", async ({ page }) => {
      await page.goto("/agent");
      const box = page
        .locator("#lifecycle")
        .getByText("Every stage works on one incident");
      await expect(box).toBeVisible();
      const parent = await box.locator("xpath=..").boundingBox();
      const text = await box.boundingBox();
      expect(text && parent).toBeTruthy();
      if (text && parent) {
        expect(text.x).toBeGreaterThanOrEqual(parent.x);
        expect(text.x + text.width).toBeLessThanOrEqual(
          parent.x + parent.width,
        );
      }
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  });
}
