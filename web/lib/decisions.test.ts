import { describe, expect, it } from "vitest";
import { DECISIONS } from "@/lib/decisions";

describe("decisions", () => {
  it("keeps all six", () => {
    expect(DECISIONS).toHaveLength(6);
  });

  it("frames the sixth around bounding generation, with the real bounds intact", () => {
    const sixth = DECISIONS[5];
    expect(sixth.title).toBe(
      "Bound generation, move the second opinion off the request path",
    );
    for (const fact of [
      "20 second budget",
      "15 second cap per attempt",
      "circuit breaker",
      "60 second deadline",
      "one-in-ten",
    ]) {
      expect(sixth.decision).toContain(fact);
    }
  });

  it("uses no em-dash anywhere", () => {
    const text = JSON.stringify(DECISIONS);
    expect(text).not.toContain("—");
  });
});
