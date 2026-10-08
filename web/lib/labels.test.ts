import { describe, expect, it } from "vitest";
import {
  BLOCK_STAGE_LABEL,
  blockStage,
  errorKindLabel,
  outcomeLabel,
} from "@/lib/labels";

describe("blockStage", () => {
  it("keeps every reason the gateway emits at its real stage", () => {
    expect(blockStage("input_rail_blocked")).toBe("input");
    expect(blockStage("no_trustworthy_sources")).toBe("retrieval");
    for (const reason of [
      "malformed_json",
      "schema_violation",
      "hallucinated_citation",
      "empty_citations_with_non_low_confidence",
      "regulated_phrase",
      "low_faithfulness",
    ]) {
      expect(blockStage(reason)).toBe("output");
    }
  });

  it("returns unknown for an unrecognized reason and labels it Unknown", () => {
    expect(blockStage("brand_new_reason")).toBe("unknown");
    expect(BLOCK_STAGE_LABEL.unknown).toBe("Unknown stage");
  });
});

describe("errorKindLabel", () => {
  it("names every error kind the gateway records, including the request deadline", () => {
    expect(errorKindLabel("request_deadline_exceeded")).toBe(
      "Request deadline exceeded",
    );
    expect(errorKindLabel("input_rail_service_unavailable")).toBe(
      "Input rail service unavailable",
    );
    expect(outcomeLabel("error", null, null, "request_deadline_exceeded")).toBe(
      "Error \u00b7 Request deadline exceeded",
    );
  });
});
