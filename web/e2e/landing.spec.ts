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
      page.getByRole("heading", { name: /Guard every answer/, level: 1 }),
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
    const intro = page.getByText(/AI reliability and evaluation platform/);
    await expect(intro).toContainText("production LLM systems");
    await expect(intro).toContainText("reference workload");
    await expect(page.locator("body")).not.toContainText(
      /sits in front of a RAG endpoint/,
    );
    const group = page.getByRole("group", {
      name: /Fin-Sentry system constellation/,
    });
    await expect(group).toContainText("AI reliability and evaluation");
    await expect(group).not.toContainText("financial RAG");
    await expect(page).toHaveTitle("Fin-Sentry");
  });

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
