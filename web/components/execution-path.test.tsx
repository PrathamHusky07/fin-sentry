import { describe, expect, it } from "vitest";
import { buildStages } from "@/components/execution-path";
import type { TraceDetailResponse } from "@/lib/trace-api";

const BASE: TraceDetailResponse = {
  app_trace_id: "t1",
  found: true,
  rag_status: "success",
  endpoint: "/rag/query",
  ticker: "AMZN",
  query: "net income",
  answer: "An answer.",
  confidence: "high",
  model_used: "model-x",
  citations: [],
  retrieved_chunk_ids: ["c1", "c2"],
  block_reason: null,
  block_rail: null,
  error_kind: null,
  error_detail: null,
  timestamp_utc: "2026-01-01T00:00:00Z",
  judge_state: "evaluated",
  flash: null,
  frontier: { sampled: false, evidence: null, note: "" },
  risingwave_connected: true,
  note: "",
};

function stage(detail: TraceDetailResponse, label: string) {
  const found = buildStages(detail).find((s) => s.label === label);
  if (!found) throw new Error(`no stage ${label}`);
  return found;
}

const flash = (status: string): TraceDetailResponse["flash"] => ({
  status,
  timestamp_utc: null,
  faithfulness_score: null,
  faithfulness_status: null,
  answer_relevance_score: null,
  answer_relevance_status: null,
  context_relevance_score: null,
  context_relevance_status: null,
});

describe("flash judge stage", () => {
  it("renders a partial verdict as partial, never as blocked", () => {
    const s = stage({ ...BASE, flash: flash("partial") }, "Flash judge");
    expect(s.status).toBe("partial");
    expect(s.summary).toContain("Partial");
  });

  it("keeps complete as passed and any other status as blocked", () => {
    expect(
      stage({ ...BASE, flash: flash("complete") }, "Flash judge").status,
    ).toBe("passed");
    expect(
      stage({ ...BASE, flash: flash("failed") }, "Flash judge").status,
    ).toBe("blocked");
  });
});

describe("unclassified stops", () => {
  it("does not attribute an unknown error_kind to generation", () => {
    const detail = {
      ...BASE,
      rag_status: "error",
      error_kind: "mystery_fault",
      answer: null,
    };
    const stages = buildStages(detail);
    expect(stages.find((s) => s.label === "Unknown stage")?.status).toBe(
      "error",
    );
    expect(stages.find((s) => s.label === "Generation")?.status).toBe(
      "unknown",
    );
  });

  it("treats an errored request with no error_kind as unclassified", () => {
    const detail = {
      ...BASE,
      rag_status: "error",
      error_kind: null,
      answer: null,
    };
    expect(stage(detail, "Unknown stage").status).toBe("error");
  });

  it("does not attribute an unknown block_reason to the output rails", () => {
    const detail = {
      ...BASE,
      rag_status: "blocked",
      block_reason: "new_rail_reason",
      answer: null,
    };
    const stages = buildStages(detail);
    expect(stages.find((s) => s.label === "Unknown stage")?.status).toBe(
      "blocked",
    );
    expect(stages.find((s) => s.label === "Output rails")?.status).toBe(
      "unknown",
    );
  });

  it("still places known errors at their stage", () => {
    const gen = {
      ...BASE,
      rag_status: "error",
      error_kind: "downstream_rate_limit",
      answer: null,
    };
    expect(stage(gen, "Generation").status).toBe("error");
    const inp = {
      ...BASE,
      rag_status: "error",
      error_kind: "input_rail_service_unavailable",
      answer: null,
    };
    expect(stage(inp, "Input rails").status).toBe("error");
    const ret = {
      ...BASE,
      rag_status: "error",
      error_kind: "vector_search_failed",
      answer: null,
    };
    expect(stage(ret, "Retrieval rail").status).toBe("error");
  });
});
