import { expect, test } from "@playwright/test";

/**
 * The shape of Live Operations after it moved to evaluation telemetry: the RAG request sections
 * are gone, the gateway reading names the health route it times, the strip describes the platform
 * and claims no state, and the calibration sentence reads the stored reading. Real stack.
 */

test.describe("Live Operations structure", () => {
  test("shows evaluation telemetry, calibration and the gateway reading, and no RAG request sections", async ({
    page,
  }) => {
    await page.goto("/operations");
    await expect(
      page.getByRole("heading", { name: "Evaluation telemetry" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Calibration" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Gateway health route" }),
    ).toBeVisible();

    for (const gone of [
      "Last recorded activity",
      "Stored request history",
      "Request buckets",
      "Request activity",
    ]) {
      await expect(page.getByText(gone, { exact: true })).toHaveCount(0);
    }
    await expect(page.locator("#activity-requests")).toHaveCount(0);
    await expect(page.locator("#activity-latency")).toHaveCount(0);
    await expect(page.getByText(/RAG latency/)).toHaveCount(0);
  });

  test("leads with the health-route figure, names the gateway health route once and stays short", async ({
    page,
  }) => {
    await page.goto("/operations");
    const probe = page.locator("[data-gateway-probe]");
    await probe.scrollIntoViewIfNeeded();
    await expect(probe).toHaveAttribute("data-gateway-probe", "recorded");
    await expect(probe).toContainText(
      "Health-route round trip, recorded probe",
    );
    await expect(probe).toContainText("ms median");
    await expect(probe).toContainText(/Recorded .* UTC/);
    await expect(probe).toContainText(
      "Each request is a GET timed until the whole response is read",
    );
    await expect(page.locator("#gateway")).toContainText(
      "gateway answers on its health route",
    );
    // The old repeated disclaimers and any RAG framing are gone from the section.
    const words = (await page.locator("#gateway").textContent()) ?? "";
    expect(words).not.toMatch(
      /RAG|no retrieval|no model|network distance|not how long/i,
    );
    expect(words).not.toContain("It is stored");
  });

  test("the strip describes the platform and claims no state", async ({
    page,
  }) => {
    await page.goto("/operations");
    const strip = page.locator("ul[aria-label='What Live Operations covers']");
    await expect(strip.locator("> li")).toHaveCount(4);
    for (const title of [
      "Quality signals",
      "Judge calibration",
      "Disagreement analysis",
      "Evidence-backed investigations",
    ]) {
      await expect(strip).toContainText(title);
    }
    const words = await strip.evaluate((el) => el.textContent ?? "");
    expect(words).not.toMatch(
      /connected|reachable|monitoring|\blive\b|\bago\b|offline|stale/i,
    );
    expect(words).not.toMatch(/\d{1,2}:\d{2}/);
    // No status dot of any color, and nothing pulsing.
    await expect(strip.locator("span.rounded-full")).toHaveCount(0);
    await expect(strip.locator(".pulse-live")).toHaveCount(0);
  });

  test("reads the stored calibration in one plain sentence", async ({
    page,
  }) => {
    await page.goto("/operations");
    const calibration = page.locator("#calibration");
    await expect(calibration).toContainText(
      /Last calibration: [A-Z][a-z]+ \d{1,2}, \d{4}\. Cohen’s kappa was \d\.\d{3} across \d+ labeled examples, /,
    );
    await expect(calibration).toContainText(/State: \w+/);
    const words = (await calibration.textContent()) ?? "";
    for (const jargon of [
      "state_as_of",
      "persisted artifact",
      "canary run read from a file",
      "The service reports",
      "Provenance",
    ]) {
      expect(words).not.toContain(jargon);
    }
  });

  test("says the telemetry is unavailable when the stream cannot be reached", async ({
    page,
  }) => {
    await page.route("**/ops/stream", (route) => route.abort());
    await page.goto("/operations");
    await expect(
      page.getByText("Evaluation telemetry is unavailable"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.locator("section[aria-label^='Flash judge']"),
    ).toHaveCount(0);
  });
});
