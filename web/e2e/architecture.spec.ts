import { expect, test } from "@playwright/test";

/**
 * /architecture, /red-team and the sticky global shell. Static content,
 * so these assert structure and the corrected claims, not live numbers.
 */
test("Architecture lays out five layers and keeps its claims source-accurate", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/architecture");
  await expect(
    page.getByRole("heading", { name: /How Fin-Sentry is built/, level: 1 }),
  ).toBeVisible();
  for (const layer of [
    "Request path",
    "Evaluation plane",
    "Event infrastructure",
    "Operational interface",
    "Incident Response Agent",
  ]) {
    await expect(
      page.getByRole("heading", { name: layer, level: 2 }),
    ).toBeVisible();
  }

  const body = page.locator("body");
  await expect(body).toContainText("gemini-3.6-flash");
  await expect(body).not.toContainText(/2\.5 Flash/);
  await expect(body).not.toContainText(/weekly/i);
  await expect(body).toContainText("not a live monitor");
  // No repo paths or dev hosts on the page.
  await expect(body).not.toContainText(
    /finsentry\/|Read from|docs\/adr|\.py\b/,
  );
  await expect(body).not.toContainText(/localhost|127\.0\.0\.1|:3000|:8000/);
  // Five distinct diagrams: a pipeline, a topology, event lanes, a hub and the agent's state machine.
  await expect(
    page.getByRole("list", { name: "The request path, left to right" }),
  ).toBeVisible();
  for (const name of [
    /evaluation plane\. A response event forks/i,
    /two lanes around a log/i,
    /operational interface as a hub/i,
  ]) {
    await expect(page.getByRole("img", { name })).toBeVisible();
  }
  // The Red Team scenario tool is the one piece that is still not registered.
  await expect(body).toContainText("not registered");
  // The MCP server registers nine read tools. No copy may still say five.
  await expect(body).toContainText("nine read tools");
  await expect(body).not.toContainText(/five read/i);

  expect(errors).toEqual([]);
});

test("Red Team renders the console, not a placeholder", async ({ page }) => {
  await page.goto("/red-team");
  await expect(
    page.getByRole("heading", { name: "Red Team", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Defenses and their scenarios" }),
  ).toBeVisible();
  await expect(page.getByText("Not built", { exact: true })).toHaveCount(0);
});

test("the global navigation stays pinned while scrolling", async ({ page }) => {
  await page.goto("/architecture");
  await page.evaluate(() => window.scrollTo(0, 1800));
  await page.waitForTimeout(200);
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav).toBeVisible();
  const box = await nav.boundingBox();
  expect(Math.abs(box?.y ?? 99)).toBeLessThan(2);
  for (const name of [
    "Overview",
    "Live Operations",
    "Investigations",
    "Agent",
    "Architecture",
    "Red Team",
  ]) {
    await expect(nav.getByRole("link", { name })).toBeVisible();
  }
});

test.describe("Architecture interactions", () => {
  test("pointing at a diagram node lights its edges, dims the rest and explains it", async ({
    page,
  }) => {
    await page.goto("/architecture");
    const diagram = page.getByRole("img", {
      name: /evaluation plane\. A response event forks/i,
    });
    await diagram.scrollIntoViewIfNeeded();
    const flash = diagram.getByRole("button", { name: /^Flash judge\./ });
    await flash.hover();
    await expect(flash).toHaveAttribute("data-state", "active");
    await expect(
      diagram.getByRole("button", { name: /^Flash verdict\./ }),
    ).toHaveAttribute("data-state", "related");
    await expect(
      diagram.getByRole("button", { name: /^Frontier judge\./ }),
    ).toHaveAttribute("data-state", "dim");
    expect(await diagram.locator('.arch-edge[data-state="lit"]').count()).toBe(
      2,
    );
    expect(
      await diagram.locator('.arch-edge[data-state="dim"]').count(),
    ).toBeGreaterThan(3);
    const strip = page
      .locator("section#evaluation-plane")
      .locator('[aria-live="polite"]');
    await expect(strip).toContainText("Flash judge");
    await expect(strip).toContainText("Connects to");
  });

  test("keyboard focus explains a node, Enter pins it and Escape clears", async ({
    page,
  }) => {
    await page.goto("/architecture");
    const diagram = page.getByRole("img", { name: /two lanes around a log/i });
    await diagram.scrollIntoViewIfNeeded();
    const browserNode = diagram.getByRole("button", { name: /^Browser\./ });
    await browserNode.focus();
    await page.keyboard.press("Tab");
    await browserNode.focus();
    await page.keyboard.press("Enter");
    await expect(browserNode).toHaveAttribute("aria-pressed", "true");
    const strip = page
      .locator("section#event-infrastructure")
      .locator('[aria-live="polite"]');
    await expect(strip).toContainText("Server-Sent Events");
    await page.keyboard.press("Escape");
    await expect(browserNode).toHaveAttribute("aria-pressed", "false");
  });

  test("the legend lights every edge of one kind", async ({ page }) => {
    await page.goto("/architecture");
    const section = page.locator("section#event-infrastructure");
    await section.scrollIntoViewIfNeeded();
    await section
      .getByRole("button", { name: /Read of persisted data/ })
      .hover();
    const diagram = section.getByRole("img", {
      name: /two lanes around a log/i,
    });
    expect(await diagram.locator('.arch-edge[data-state="lit"]').count()).toBe(
      4,
    );
  });

  test("the MCP layer leads with MCP, and the reasons open and close", async ({
    page,
  }) => {
    await page.goto("/architecture");
    await expect(
      page.getByRole("heading", {
        name: "MCP & operational interface",
        level: 2,
      }),
    ).toBeVisible();
    await expect(page.locator("#main-content header").first()).toContainText(
      /the tool that would run Red Team scenarios is not registered/i,
    );
    await page
      .getByRole("link", { name: /MCP & operational interface/ })
      .first()
      .click();
    await expect(page).toHaveURL(/#operational-interface$/);

    const second = page
      .locator("section#operational-interface")
      .getByRole("button", { name: /Why the gateway emits OpenTelemetry/ });
    const first = page
      .locator("section#operational-interface")
      .getByRole("button", { name: /Why MCP/ });
    await expect(first).toHaveAttribute("aria-expanded", "true");
    await expect(second).toHaveAttribute("aria-expanded", "false");
    await second.click();
    await expect(second).toHaveAttribute("aria-expanded", "true");
    await first.click();
    await expect(first).toHaveAttribute("aria-expanded", "false");
  });
});

test("browser tab titles use one separator and no em-dash", async ({
  page,
}) => {
  const titles: [string, string][] = [
    ["/architecture", "Architecture | Fin-Sentry"],
    ["/investigations", "Investigations | Fin-Sentry"],
    ["/operations", "Live Operations | Fin-Sentry"],
    ["/overview", "Overview | Fin-Sentry"],
    ["/red-team", "Red Team | Fin-Sentry"],
    ["/agent", "Agent | Fin-Sentry"],
  ];
  for (const [route, title] of titles) {
    await page.goto(route);
    await expect(page).toHaveTitle(title);
  }
});

test.describe("the Incident Response Agent layer", () => {
  test("is a fifth layer drawn as a control-flow state machine", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await page.goto("/architecture");
    await expect(
      page.getByRole("heading", {
        name: "Incident Response Agent",
        level: 2,
      }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("navigation", { name: "Architecture layers" })
        .locator("li"),
    ).toHaveCount(5);
    const diagram = page.getByRole("img", {
      name: /Incident Response Agent as a control-flow state machine/i,
    });
    await diagram.scrollIntoViewIfNeeded();
    await expect(diagram).toBeVisible();
    await expect(diagram).toContainText("Evidence boundary");
    for (const node of [
      /^Trigger\./,
      /^Plan\./,
      /^Assess\./,
      /^Abstention\./,
    ]) {
      await expect(diagram.getByRole("button", { name: node })).toBeVisible();
    }
    expect(errors).toEqual([]);
  });

  test("pointing at Assess lights its connections and explains the state", async ({
    page,
  }) => {
    await page.goto("/architecture");
    const section = page.locator("section#incident-response-agent");
    const diagram = section.getByRole("img");
    await diagram.scrollIntoViewIfNeeded();
    await diagram.getByRole("button", { name: /^Assess\./ }).hover();
    await expect(
      diagram.getByRole("button", { name: /^Validate\./ }),
    ).toHaveAttribute("data-state", "related");
    await expect(
      diagram.getByRole("button", { name: /^Trigger\./ }),
    ).toHaveAttribute("data-state", "dim");
    const strip = section.locator('[aria-live="polite"]');
    await expect(strip).toContainText("Deterministic evaluators");
  });

  test("keyboard selection pins the model's node and Escape clears it", async ({
    page,
  }) => {
    await page.goto("/architecture");
    const section = page.locator("section#incident-response-agent");
    const planner = section.getByRole("button", { name: /^Planner\./ });
    await planner.scrollIntoViewIfNeeded();
    await planner.focus();
    await page.keyboard.press("Enter");
    await expect(planner).toHaveAttribute("aria-pressed", "true");
    await expect(section.locator('[aria-live="polite"]')).toContainText(
      "The model proposes",
    );
    await page.keyboard.press("Escape");
    await expect(planner).toHaveAttribute("aria-pressed", "false");
  });

  test("a narrow screen gets the outline instead of the diagram", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/architecture");
    const section = page.locator("section#incident-response-agent");
    await section.scrollIntoViewIfNeeded();
    await expect(section.getByRole("img")).toBeHidden();
    await expect(section.getByText("Continue or stop")).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test("the interface hub draws all nine read tools and no scenario-running tool", async ({
  page,
}) => {
  await page.goto("/architecture");
  const diagram = page.getByRole("img", {
    name: /operational interface as a hub/i,
  });
  await diagram.scrollIntoViewIfNeeded();
  await expect(diagram).toHaveAccessibleName(/nine read tools/);
  for (const tool of [
    "Failing traces",
    "Guardrail decisions",
    "Judge scores",
    "Injection search",
    "Drift report",
    "Trace search",
    "Trace detail",
    "Red Team executions",
    "Red Team execution",
  ]) {
    await expect(
      diagram.getByRole("button", { name: new RegExp(`^${tool}$`) }),
    ).toHaveCount(1);
  }
  // The scenario tool stays dashed and unregistered.
  await expect(
    diagram.getByRole("button", { name: /^Scenario tool\./ }),
  ).toBeVisible();
});

test("the agent is named in the jump rail, the layer card and the primary navigation", async ({
  page,
}) => {
  await page.goto("/architecture");
  await expect(
    page
      .getByRole("navigation", { name: "Jump to a layer" })
      .getByRole("link", { name: /Incident Response Agent/ }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Architecture layers" })
      .getByRole("link", { name: /Incident Response Agent/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", {
      name: "Agent",
      exact: true,
    }),
  ).toBeVisible();
});
