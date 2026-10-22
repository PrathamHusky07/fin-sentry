import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { GENERATION_BOUNDS } from "@/lib/generation-bounds";
import { summarizeGeneration } from "@/lib/generation-data";
import type { TraceListItem } from "@/lib/trace-api";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const read = (rel: string) => readFileSync(`${ROOT}/${rel}`, "utf8");

function numberAfter(source: string, pattern: RegExp): number {
  const m = source.match(pattern);
  if (!m) throw new Error(`pattern not found: ${pattern}`);
  return Number(m[1]);
}

describe("generation bounds", () => {
  const gateway = read("finsentry/gateway/main.py");
  const breaker = read("finsentry/gateway/circuit_breaker.py");

  it("match the constants in the gateway source", () => {
    expect(GENERATION_BOUNDS.callBudgetSeconds).toBe(
      numberAfter(gateway, /^_RAG_BUDGET: float = ([\d.]+)/m),
    );
    expect(GENERATION_BOUNDS.attemptCapSeconds).toBe(
      numberAfter(gateway, /^_ATTEMPT_CAP: float = ([\d.]+)/m),
    );
    expect(GENERATION_BOUNDS.requestDeadlineSeconds).toBe(
      numberAfter(gateway, /^_REQUEST_DEADLINE: float = ([\d.]+)/m),
    );
  });

  it("match the breaker the gateway builds", () => {
    expect(GENERATION_BOUNDS.breakerFailures).toBe(
      numberAfter(gateway, /failure_threshold=(\d+)/),
    );
    expect(GENERATION_BOUNDS.breakerOpenSeconds).toBe(
      numberAfter(gateway, /recovery_timeout=([\d.]+)/),
    );
    // The class defaults agree, so a caller that builds one without arguments is not different.
    expect(GENERATION_BOUNDS.breakerFailures).toBe(
      numberAfter(breaker, /failure_threshold: int = (\d+)/),
    );
  });
});

function trace(
  id: string,
  status: string,
  reason: string | null = null,
): TraceListItem {
  return {
    app_trace_id: id,
    timestamp_utc: "2026-10-22T01:00:00Z",
    endpoint: "/v1/rag/query",
    ticker: "AMZN",
    query: "q",
    rag_status: status,
    block_reason: reason,
    judge_state: "never_evaluated",
    frontier_sampled: false,
  };
}

describe("summarizeGeneration", () => {
  it("counts only what the schema rail rejected, and keeps the newest example", () => {
    const record = summarizeGeneration([
      trace("a", "blocked", "malformed_json"),
      trace("b", "blocked", "malformed_json"),
      trace("c", "blocked", "schema_violation"),
      trace("d", "blocked", "low_faithfulness"),
      trace("e", "blocked", "input_rail_blocked"),
      trace("f", "success"),
      trace("g", "error"),
    ]);
    expect(record.total).toBe(7);
    expect(record.delivered).toBe(1);
    expect(record.errored).toBe(1);
    expect(record.rejected).toEqual({
      malformed_json: 2,
      schema_violation: 1,
      hallucinated_citation: 0,
      empty_citations_with_non_low_confidence: 0,
    });
    // The list is newest first, so the first match is the newest.
    expect(record.example.malformed_json).toBe("a");
    expect(record.example.schema_violation).toBe("c");
    expect(record.example.hallucinated_citation).toBeUndefined();
    expect(record.recentDelivered).toEqual(["f"]);
  });

  it("keeps only the newest delivered requests as example candidates", () => {
    const many = Array.from({ length: 12 }, (_, i) =>
      trace(`t${i}`, "success"),
    );
    const record = summarizeGeneration(many);
    expect(record.delivered).toBe(12);
    expect(record.recentDelivered).toEqual([
      "t0",
      "t1",
      "t2",
      "t3",
      "t4",
      "t5",
      "t6",
      "t7",
    ]);
  });

  it("reports a full scan as a window and a short one as complete", () => {
    expect(summarizeGeneration([trace("a", "success")], 1).scanIsWindow).toBe(
      true,
    );
    expect(summarizeGeneration([trace("a", "success")], 5).scanIsWindow).toBe(
      false,
    );
  });
});
