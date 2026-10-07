import { describe, expect, it } from "vitest";
import { groupKey } from "@/lib/overview-data";

describe("groupKey", () => {
  it("keeps distinct ticker and query pairs apart when their concatenations match", () => {
    expect(groupKey({ ticker: "A", query: "B C" })).not.toBe(
      groupKey({ ticker: "A B", query: "C" }),
    );
  });

  it("keeps a missing ticker apart from an empty-string ticker", () => {
    expect(groupKey({ ticker: null, query: "q" })).not.toBe(
      groupKey({ ticker: "", query: "q" }),
    );
  });

  it("is stable for the same pair", () => {
    expect(groupKey({ ticker: "AMZN", query: "net income" })).toBe(
      groupKey({ ticker: "AMZN", query: "net income" }),
    );
  });
});
