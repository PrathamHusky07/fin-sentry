import { expect, test } from "@playwright/test";

/**
 * The presentation layer (/). Needs only the web app: nothing on this page
 * reads the gateway. Deterministic structural assertions: the constellation
 * hero, the interactive system map, the decision navigator, the evidence
 * frames, the truth-boundary copy rules, and the CTAs.
 */
test.describe("Landing page", () => {
  test("renders the hero, the system map, the navigator and the evidence frames", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/");

    await expect(
      page.getByRole("heading", {
        name: "Score the answer. Audit the judge. Explain the failure from the record.",
        level: 1,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("group", { name: /Fin-Sentry system constellation/ }),
    ).toBeVisible();

    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    await expect(map).toBeVisible();
    for (const stage of [
      "Client",
      "Gateway",
      "Input rails",
      "Retrieval",
      "Generation",
      "Output rails",
      "Response",
      "Event stream",
      "Flash judge",
      "Deterministic sampler",
      "Frontier judge",
      "Calibration",
      "RisingWave",
      "Investigations",
      "MCP server",
    ]) {
      await expect(
        map.getByRole("button", { name: new RegExp(`^${stage}\\.`) }),
      ).toBeVisible();
    }

    await expect(
      page.getByRole("heading", { name: /Six decisions/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /real disagreement/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Overview command center/i }),
    ).toBeVisible();

    expect(errors).toEqual([]);
  });

  test("the hero presents an AI reliability platform with financial RAG as the reference workload", async ({
    page,
  }) => {
    await page.goto("/");
    const intro = page.getByText(
      /Fin-Sentry is an AI reliability and evaluation platform/,
    );
    await expect(intro).toContainText("second-opinion judge");
    await expect(intro).toContainText("calibrated independently");
    await expect(intro).toContainText("reference workload");
    // The hero leads with reliability, evaluation and incident reconstruction that can abstain,
    // makes no claim that every execution is preserved, and does not call financial RAG the
    // only workload.
    await expect(intro).toContainText("incident agent");
    await expect(intro).toContainText(
      "abstains when they cannot support an explanation",
    );
    await expect(intro).toContainText("can be inspected");
    await expect(intro).not.toContainText("only workload");
    await expect(intro).not.toContainText(/every execution/i);
    await expect(intro).not.toContainText("guarantee");
    await expect(intro).not.toContainText("—");
    // Four sentences at most.
    const sentences = ((await intro.innerText()).match(/\.(\s|$)/g) ?? [])
      .length;
    expect(sentences).toBeLessThanOrEqual(4);
    await expect(page.locator('head meta[name="description"]')).toHaveAttribute(
      "content",
      /evidence-bounded agent/,
    );
    // The rejected framing is gone from the page and from the headline.
    await expect(page.locator("body")).not.toContainText(
      /sits in front of an? (LLM|RAG) endpoint/,
    );
    await expect(page.locator("body")).not.toContainText(
      "Make every AI answer show its work",
    );
    await expect(page.locator("body")).not.toContainText("AI answers are easy");
    const group = page.getByRole("group", {
      name: /Fin-Sentry system constellation/,
    });
    await expect(group).toContainText("AI reliability and evaluation");
    await expect(group).not.toContainText("financial RAG");
    await expect(page).toHaveTitle("Fin-Sentry");
  });

  test("the first fold moves when motion is allowed and holds still when it is not", async ({
    page,
  }) => {
    const fold = async () =>
      page.evaluate(() => {
        const name = (selector: string): string => {
          const el = document.querySelector(selector);
          return el ? getComputedStyle(el).animationName : "missing";
        };
        return {
          line: name(".hero-in"),
          fieldA: name(".hero-field-a"),
          fieldB: name(".hero-field-b"),
          fieldC: name(".hero-field-c"),
          aurora: name(".hero-aurora"),
          scan: name(".hero-scan-band"),
          sweep: name(".hero-sweep"),
          breathe: name(".cn-breathe"),
        };
      });
    const judge = (p: typeof page) =>
      p
        .getByRole("group", { name: /Fin-Sentry system constellation/ })
        .getByRole("button", { name: /^Judge\./ });

    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto("/");
    const moving = await fold();
    expect(moving.line).toBe("rise");
    expect(moving.fieldA).toBe("field-drift-a");
    expect(moving.fieldB).toBe("field-drift-b");
    expect(moving.fieldC).toBe("field-drift-c");
    expect(moving.aurora).toBe("aurora-flow");
    expect(moving.scan).toBe("scan-sweep");
    expect(moving.sweep).toBe("sweep-turn");
    expect(moving.breathe).toBe("cn-breathe");
    // Energy runs along the selected path only, and stops when the pointer leaves.
    await expect(page.locator(".cn-flow")).toHaveCount(0);
    await judge(page).hover();
    expect(await page.locator(".cn-flow").count()).toBeGreaterThan(0);
    await expect(page.locator(".cn-flow").first()).toBeVisible();
    await page.mouse.move(5, 5);
    await expect(page.locator(".cn-flow")).toHaveCount(0);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const still = await fold();
    expect(still.fieldA).toBe("none");
    expect(still.fieldB).toBe("none");
    expect(still.fieldC).toBe("none");
    expect(still.aurora).toBe("none");
    expect(still.scan).toBe("none");
    expect(still.sweep).toBe("none");
    expect(still.breathe).toBe("none");
    await judge(page).hover();
    // The selection still lights its lines, but nothing travels along them.
    for (const flow of await page.locator(".cn-flow").all()) {
      await expect(flow).toBeHidden();
    }
  });

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 375, height: 812 },
  ]) {
    test(`the rendered first fold at ${viewport.width}px changes over time with motion and is identical without it`, async ({
      page,
    }) => {
      test.setTimeout(45_000);
      await page.setViewportSize(viewport);
      const snap = async () =>
        page.screenshot({
          clip: { x: 0, y: 0, width: viewport.width, height: viewport.height },
        });
      const headingBox = () =>
        page.getByRole("heading", { level: 1 }).boundingBox();

      // The intro settles within about two and a half seconds. After that only the ambient
      // layers can change a pixel.
      await page.emulateMedia({ reducedMotion: "no-preference" });
      await page.goto("/");
      await page.waitForTimeout(3500);
      const first = await snap();
      const box = await headingBox();
      await page.waitForTimeout(4000);
      const second = await snap();
      expect(Buffer.compare(first, second)).not.toBe(0);
      // The text does not move while the background does.
      expect(await headingBox()).toEqual(box);

      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/");
      await page.waitForTimeout(1500);
      const still = await snap();
      await page.waitForTimeout(4000);
      expect(Buffer.compare(still, await snap())).toBe(0);
    });
  }

  test("the decision navigator lists six decisions and selecting one changes the panel", async ({
    page,
  }) => {
    await page.goto("/");
    const section = page.getByRole("region", { name: /Six decisions/ });
    const controls = section.locator("ul button");
    await expect(controls).toHaveCount(6);
    const first = section.locator("#decision-panel-0");
    const third = section.locator("#decision-panel-2");
    await expect(first).toContainText("Problem");
    await expect(first).toBeVisible();
    await expect(third).toHaveCSS("opacity", "0");

    await controls.nth(2).click();
    await expect(third).toHaveCSS("opacity", "1");
    for (const part of ["Problem", "Decision", "Tradeoff", "Consequence"]) {
      await expect(third).toContainText(part);
    }
    await expect(third).toContainText(/judge pipeline error/i);
    await expect(first).toHaveCSS("opacity", "0");
    await expect(controls.nth(2)).toHaveAttribute("aria-current", "true");

    // Arrow keys move the selection along with focus.
    await controls.nth(2).press("ArrowDown");
    await expect(controls.nth(3)).toBeFocused();
    await expect(controls.nth(3)).toHaveAttribute("aria-current", "true");
    await controls.nth(5).click();
    await expect(controls.nth(5)).toContainText(
      "Bound generation, move the second opinion off the request path",
    );
    await expect(page.locator("#decision-panel-5")).toContainText(
      "20 second budget",
    );
    await expect(page.getByText(/Keep generation local/)).toHaveCount(0);
    await expect(page.getByText(/Known limits/i)).toHaveCount(0);
    await expect(page.getByText(/does not do yet/i)).toHaveCount(0);
  });

  test("pointing at a constellation node lights what it touches and dims the rest", async ({
    page,
  }) => {
    await page.goto("/");
    const group = page.getByRole("group", {
      name: /Fin-Sentry system constellation/,
    });
    const node = (name: string) =>
      group.getByRole("button", { name: new RegExp(`^${name}\\.`) });
    await node("Judge").hover();
    await expect(node("Generate").locator("xpath=.")).toHaveAttribute(
      "data-state",
      "related",
    );
    await expect(node("Calibrate")).toHaveAttribute("data-state", "related");
    await expect(node("Guard")).toHaveAttribute("data-state", "dim");
    await expect(node("MCP")).toHaveAttribute("data-state", "dim");
    await expect(node("Judge")).toHaveAttribute("data-state", "active");
    await expect(page.getByText("Touches", { exact: false })).toContainText(
      "Generate, Calibrate, Agent",
    );
    await page.mouse.move(5, 5);
    await expect(node("Guard")).toHaveAttribute("data-state", "rest");
  });

  test("the Agent node says what the agent reads and that every execution is kept", async ({
    page,
  }) => {
    await page.goto("/");
    const group = page.getByRole("group", {
      name: /Fin-Sentry system constellation/,
    });
    await group.getByRole("button", { name: /^Agent\./ }).hover();
    const body = page.locator("body");
    await expect(body).toContainText(/examines persisted evidence/);
    await expect(body).toContainText(/Every execution stays stored/);
    await group.getByRole("button", { name: /^MCP\./ }).hover();
    await expect(body).toContainText(/Nine read-only tools/);
    await expect(body).not.toContainText(/five read/i);
  });

  test("an evidence frame reveals its action on hover and scrolls the capture", async ({
    page,
  }) => {
    await page.goto("/");
    const action = page.getByRole("link", { name: /Open command center/ });
    await expect(action).toHaveCSS("opacity", "0");
    const frame = page
      .getByRole("region", { name: /Scrollable capture of \/overview/ })
      .locator("xpath=ancestor::div[contains(@class,'lift')][1]");
    await frame.scrollIntoViewIfNeeded();
    await frame.hover();
    await expect(action).toHaveCSS("opacity", "1");
    await expect(action).toHaveAttribute("href", "/overview");
  });

  test("reduced motion removes the hero reveal", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const nodeWrapper = page
      .getByRole("group", { name: /Fin-Sentry system constellation/ })
      .locator(".cn-node")
      .first();
    await expect(nodeWrapper).toHaveCSS("animation-name", "none");
  });

  test("hovering a station brightens it and fills the caption strip", async ({
    page,
  }) => {
    await page.goto("/");
    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    const sampler = map.getByRole("button", {
      name: /^Deterministic sampler\./,
    });
    await sampler.hover();
    const detail = page.locator("#topology-detail");
    await expect(detail).toContainText("Deterministic sampler");
    await expect(detail).toContainText(/trace id/i);
    await expect(detail).toContainText("Why it exists");
    // The active station grows; a station far from it recedes.
    const grown = await sampler
      .locator("circle.topo-grow")
      .evaluate((el) => getComputedStyle(el).transform);
    expect(grown).not.toBe("none");
    const unrelated = map.getByRole("button", { name: /^MCP server\./ });
    await expect
      .poll(async () =>
        Number(await unrelated.evaluate((el) => getComputedStyle(el).opacity)),
      )
      .toBeLessThan(0.5);
  });

  test("calibration is drawn as measuring the frontier judge, in the arrow's direction", async ({
    page,
  }) => {
    await page.goto("/");
    const map = page.getByRole("group", { name: /Fin-Sentry system map/ });
    const label = map.getByText("measured by", { exact: true });
    await expect(label).toBeVisible();
    const frontier = await map
      .getByRole("button", { name: /^Frontier judge\./ })
      .boundingBox();
    const calibration = await map
      .getByRole("button", { name: /^Calibration\./ })
      .boundingBox();
    const labelBox = await label.boundingBox();
    const frontierRight = (frontier?.x ?? 0) + (frontier?.width ?? 0) / 2;
    expect(frontierRight).toBeLessThan(labelBox?.x ?? 0);
    expect((labelBox?.x ?? 0) + (labelBox?.width ?? 0)).toBeLessThan(
      (calibration?.x ?? 0) + (calibration?.width ?? 0),
    );
  });

  test("copy rules: current model names, no dev host, no repo paths, no stale claims", async ({
    page,
  }) => {
    await page.goto("/");
    const body = page.locator("body");
    await expect(body).toContainText("gemini-3.6-flash");
    await expect(body).not.toContainText(/2\.5 Flash/);
    await expect(body).not.toContainText(/weekly/i);
    await expect(body).not.toContainText(/runs locally/i);
    await expect(body).not.toContainText(/localhost|127\.0\.0\.1|:3000|:8000/);
    await expect(body).not.toContainText(/finsentry\/|docs\/adr|\.py\b/);
    await expect(body).not.toContainText(/sha256\(trace id\)/);
    await expect(body).not.toContainText(/POST \/v1/);
    await expect(body).not.toContainText(/Hover or focus a stage/);
  });

  test("the wordmark links to / and the CTA reaches the command center", async ({
    page,
  }) => {
    await page.goto("/overview");
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Fin-Sentry" })
      .click();
    await expect(page).toHaveURL(/\/$/);

    await page.getByRole("link", { name: "Open the command center" }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(
      page.getByRole("heading", { name: "Overview", level: 1 }),
    ).toBeVisible();
  });
});
