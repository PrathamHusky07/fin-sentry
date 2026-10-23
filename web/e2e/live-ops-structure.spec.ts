import { expect, test } from "@playwright/test";

/**
 * The shape of Live Operations after it moved to evaluation telemetry: the RAG request sections
 * are gone, the gateway reading is labeled for what it times, the strip describes the platform
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

  test("labels the gateway reading as the health-route round trip and says what was timed", async ({
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
    await expect(probe).toContainText("It is stored, so it stays here");
    await expect(probe).toContainText(
      "from the probe sending a GET to the gateway health route until it had read the whole response",
    );
    await expect(probe).toContainText("no retrieval and no model");
    await expect(page.locator("#gateway")).toContainText(
      "not how long an evaluation or an answer takes",
    );
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
