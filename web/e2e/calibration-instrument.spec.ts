import { expect, test } from "@playwright/test";

/**
 * The calibration instrument on /operations. Needs the real stack, because
 * the markers are drawn from the persisted calibration reading. Each marker
 * explains itself on hover or focus, and a click or tap pins the
 * explanation so it survives the pointer leaving and works on touch.
 */

async function openInstrument(page: import("@playwright/test").Page) {
  await page.goto("/operations");
  const group = page.getByRole("group", { name: /Kappa .* on a scale/ });
  await expect(group).toBeVisible();
  await group.scrollIntoViewIfNeeded();
  const tip = group.locator("[aria-live=polite]");
  const marker = (name: string) =>
    group.getByRole("button", { name: new RegExp(`^${name}`) });
  return { group, tip, marker };
}

test("hovering and focusing a marker explains it, and leaving clears it", async ({
  page,
}) => {
  const { tip, marker } = await openInstrument(page);
  await expect(tip).toBeEmpty();

  // The last reading sits close to the recovery line, so aim at the outer
  // edge of the recovery marker where the two hit areas do not overlap.
  await marker("Recovery").hover({ position: { x: 40, y: 22 }, force: true });
  await expect(tip).toContainText("Recovery");
  await expect(tip).toContainText(/recovered only when agreement/);
  await page.mouse.move(2, 2);
  await expect(tip).toBeEmpty();

  // Tab into the marker so the browser treats it as keyboard focus.
  await marker("Drift entry").focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(marker("Drift entry")).toBeFocused();
  await expect(tip).toContainText("Drift entry");
  await marker("Drift entry").blur();
  await expect(tip).toBeEmpty();
});

test("a click pins the explanation, a second click or Escape clears it", async ({
  page,
}) => {
  const { tip, marker } = await openInstrument(page);

  await marker("Healthy baseline").click();
  await page.mouse.move(2, 2);
  await expect(tip).toContainText("Healthy baseline");
  await expect(marker("Healthy baseline")).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await marker("Drift entry").click();
  await page.mouse.move(2, 2);
  await expect(tip).toContainText("Drift entry");
  await expect(marker("Healthy baseline")).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  await marker("Drift entry").click();
  await page.mouse.move(2, 2);
  await expect(tip).toBeEmpty();

  await marker("Drift entry").click();
  await expect(marker("Drift entry")).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await page.mouse.move(2, 2);
  await expect(tip).toBeEmpty();
});

test.describe("on a touch device", () => {
  test.use({ viewport: { width: 375, height: 900 }, hasTouch: true });

  test("tapping each marker leaves its explanation visible", async ({
    page,
  }) => {
    const { tip, marker } = await openInstrument(page);
    for (const name of ["Drift entry", "Healthy baseline"]) {
      await marker(name).tap();
      await expect(tip).toContainText(name);
    }
  });
});
