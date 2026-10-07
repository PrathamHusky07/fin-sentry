import { describe, expect, it } from "vitest";
import {
  COMPACT,
  CONCEPTS,
  CONCEPT_BY_ID,
  WIDE,
  conceptLinks,
  placeConcepts,
} from "@/lib/constellation";

describe("constellation data", () => {
  it("keeps every relation symmetric and never self-referential", () => {
    for (const concept of CONCEPTS) {
      expect(concept.related).not.toContain(concept.id);
      for (const other of concept.related) {
        expect(CONCEPT_BY_ID[other].related).toContain(concept.id);
      }
    }
  });

  it("lists each relation exactly once", () => {
    const links = conceptLinks();
    const keys = links.map(([a, b]) => [a, b].sort().join("|"));
    expect(new Set(keys).size).toBe(keys.length);
    const total = CONCEPTS.reduce((sum, c) => sum + c.related.length, 0);
    expect(links).toHaveLength(total / 2);
  });

  it("covers the seven concepts of the system in reading order", () => {
    expect(CONCEPTS.map((c) => c.id)).toEqual([
      "guard",
      "retrieve",
      "generate",
      "judge",
      "calibrate",
      "investigate",
      "mcp",
    ]);
  });
});

describe("constellation layout", () => {
  for (const [name, layout] of [
    ["wide", WIDE],
    ["compact", COMPACT],
  ] as const) {
    it(`keeps every ${name} node fully inside its viewBox with room for labels`, () => {
      const placed = placeConcepts(layout);
      for (const concept of CONCEPTS) {
        const { x, y, r } = placed[concept.id];
        expect(x - r).toBeGreaterThan(0);
        expect(x + r).toBeLessThan(layout.w);
        expect(y - r).toBeGreaterThan(0);
        // A label and its role line sit below the node on the wide layout.
        const below = layout.labels ? 44 : 0;
        expect(y + r + below).toBeLessThan(layout.h);
      }
    });

    it(`keeps every ${name} node clear of the identity disc`, () => {
      const placed = placeConcepts(layout);
      for (const concept of CONCEPTS) {
        const { x, y, r } = placed[concept.id];
        const distance = Math.hypot(x - layout.cx, y - layout.cy);
        expect(distance - r).toBeGreaterThan(layout.core + 20);
      }
    });
  }
});
