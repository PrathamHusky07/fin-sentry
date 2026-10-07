import { describe, expect, it } from "vitest";
import { EDGES } from "@/lib/architecture-data";
import { BOX, EDGE_PATH, edgeKey } from "@/lib/topology-layout";

describe("calibration edge direction", () => {
  it("runs from the frontier judge to calibration, never the reverse", () => {
    const measure = EDGES.filter((e) => e.kind === "measure");
    expect(measure).toHaveLength(1);
    expect(measure[0].from).toBe("frontier");
    expect(measure[0].to).toBe("calibration");
    expect(measure[0].label).toBe("measured by");
    expect(
      EDGES.some((e) => e.from === "calibration" && e.to === "frontier"),
    ).toBe(false);
  });

  it("draws the arrow from the frontier marker to the calibration marker", () => {
    const path = EDGE_PATH[edgeKey("frontier", "calibration")];
    const [, startX] = /^M(\d+),/.exec(path) ?? [];
    const [, endX] = /H(\d+)$/.exec(path) ?? [];
    expect(Number(startX)).toBeGreaterThan(BOX.frontier.cx);
    expect(Number(startX)).toBeLessThan(BOX.calibration.cx);
    expect(Number(endX)).toBeGreaterThan(Number(startX));
    expect(Number(endX)).toBeLessThan(BOX.calibration.cx);
  });

  it("has a drawn path for every edge", () => {
    for (const edge of EDGES) {
      expect(EDGE_PATH[edgeKey(edge.from, edge.to)]).toBeTruthy();
    }
  });
});
