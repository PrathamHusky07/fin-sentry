import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ROUTES } from "@/lib/routes";

const APP = join(__dirname, "..", "app");

describe("ROUTES", () => {
  it("names a page for every link the top bar and the footer render", () => {
    for (const route of ROUTES) {
      expect(existsSync(join(APP, route.href, "page.tsx")), route.href).toBe(
        true,
      );
    }
  });

  it("lists each route once", () => {
    expect(new Set(ROUTES.map((r) => r.href)).size).toBe(ROUTES.length);
  });
});
