import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TraceCaseFile, citedChunkCount } from "@/components/trace-case-file";
import type { TraceDetailResponse } from "@/lib/trace-api";

const DETAIL: TraceDetailResponse = {
  app_trace_id: "t1",
  found: true,
  rag_status: "success",
  endpoint: "/rag/query",
  ticker: "AMZN",
  query: "net income",
  answer: "An answer.",
  confidence: "high",
  model_used: "model-x",
  citations: [
    { chunk_id: "c1", quote: "first" },
    { chunk_id: "c1", quote: "second quote of the same chunk" },
    { chunk_id: "c2", quote: "other" },
  ],
  retrieved_chunk_ids: ["c1", "c2", "c3"],
  block_reason: null,
  block_rail: null,
  error_kind: null,
  error_detail: null,
  timestamp_utc: "2026-01-01T00:00:00Z",
  judge_state: "never_evaluated",
  flash: null,
  frontier: { sampled: false, evidence: null, note: "" },
  risingwave_connected: true,
  note: "",
};

describe("cited chunk count", () => {
  it("counts distinct chunks, not raw citation entries", () => {
    expect(citedChunkCount(DETAIL)).toBe(2);
  });

  it("shows the distinct count in the answer footer and the evidence summary", () => {
    const html = renderToStaticMarkup(<TraceCaseFile detail={DETAIL} />);
    expect(html).toContain("2 cited in the answer");
    expect(html).not.toContain("3 cited in the answer");
    expect(html).toMatch(/Cites\s*(<!-- -->)?2(<!-- -->)?\s*of\s*(<!-- -->)?3/);
  });
});
