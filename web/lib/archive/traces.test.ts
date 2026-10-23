import { describe, expect, it } from "vitest";
import { calibrationHealth } from "@/lib/archive/calibration";
import { metricsSnapshot } from "@/lib/archive/snapshot";
import {
  traceDetail,
  traceList,
  type TraceListParams,
} from "@/lib/archive/traces";

// Every expected value below was computed from docs/demo-archive with a separate Python
// script, not read back from the code under test.

const ALL: TraceListParams = {
  limit: 500,
  offset: 0,
  ticker: null,
  status: null,
  q: null,
  judgeState: null,
  frontierSampled: null,
  disagreement: null,
};

describe("traceList", () => {
  it("lists the 291 real requests and leaves the 42 regression probes out", async () => {
    const list = await traceList(ALL);
    expect(list.traces).toHaveLength(291);
    expect(
      list.traces.some((t) =>
        t.query.startsWith("duplicate-verdict regression probe "),
      ),
    ).toBe(false);
    expect(list.next_offset).toBeNull();
  });

  it("puts the newest request first with its original time", async () => {
    const list = await traceList({ ...ALL, limit: 1 });
    expect(list.traces[0]).toMatchObject({
      app_trace_id: "b357b1c2-804d-43ef-8b1d-7f1eb5f01287",
      timestamp_utc: "2026-10-22T20:00:39.115184Z",
      rag_status: "error",
      ticker: "AMZN",
      judge_state: "blocked_before_evaluation",
    });
    expect(list.next_offset).toBe(1);
  });

  it("counts the five judge states the way the dashboard classifies them", async () => {
    const { traces } = await traceList(ALL);
    const counts: Record<string, number> = {};
    for (const t of traces)
      counts[t.judge_state] = (counts[t.judge_state] ?? 0) + 1;
    expect(counts).toEqual({
      evaluated: 248,
      partially_evaluated: 4,
      judge_failed: 3,
      blocked_before_evaluation: 36,
    });
  });

  it("marks 129 requests as frontier sampled", async () => {
    const { traces } = await traceList(ALL);
    expect(traces.filter((t) => t.frontier_sampled)).toHaveLength(129);
    const only = await traceList({ ...ALL, frontierSampled: true });
    expect(only.traces).toHaveLength(129);
  });

  it("finds no flash and frontier disagreement, because that trace expired from the topics", async () => {
    expect((await traceList({ ...ALL, disagreement: true })).traces).toEqual(
      [],
    );
    expect(
      (await traceList({ ...ALL, disagreement: false })).traces,
    ).toHaveLength(291);
  });

  it("filters on the delivery status, the ticker and the judge state", async () => {
    expect(
      (await traceList({ ...ALL, status: "blocked" })).traces,
    ).toHaveLength(34);
    expect((await traceList({ ...ALL, status: "error" })).traces).toHaveLength(
      2,
    );
    expect(
      (await traceList({ ...ALL, judgeState: "judge_failed" })).traces,
    ).toHaveLength(3);
    const amzn = await traceList({ ...ALL, ticker: "AMZN" });
    expect(amzn.traces).toHaveLength(8);
  });

  it("matches a search on the query or the trace id, ignoring case", async () => {
    const byId = await traceList({ ...ALL, q: "B357B1C2" });
    expect(byId.traces.map((t) => t.app_trace_id)).toEqual([
      "b357b1c2-804d-43ef-8b1d-7f1eb5f01287",
    ]);
    expect(
      (await traceList({ ...ALL, q: "no such text anywhere" })).traces,
    ).toEqual([]);
  });

  it("pages with an offset and reports the next one only when the page is full", async () => {
    const first = await traceList({ ...ALL, limit: 100 });
    const last = await traceList({ ...ALL, limit: 100, offset: 200 });
    expect(first.next_offset).toBe(100);
    expect(last.traces).toHaveLength(91);
    expect(last.next_offset).toBeNull();
  });

  it("rejects a limit outside 1 to 500", async () => {
    await expect(traceList({ ...ALL, limit: 0 })).rejects.toThrow(RangeError);
    await expect(traceList({ ...ALL, limit: 501 })).rejects.toThrow(RangeError);
  });
});

describe("traceDetail", () => {
  it("returns a delivered answer with its flash verdict and the real frontier evidence", async () => {
    const d = await traceDetail("54cd64af-d7da-4b9e-8ffa-e46da1e27d6b");
    expect(d.found).toBe(true);
    expect(d.frontier.sampled).toBe(true);
    expect(d.frontier.evidence).toMatchObject({
      judge_id: "gemini-rubric",
      faithfulness_score: 1,
      verdict: "ensemble_supported",
      evaluation_ts: "2026-10-08T18:43:23.090055Z",
    });
    expect(d.frontier.evidence?.rubric_reasoning).toContain(
      "exact net sales figure",
    );
    expect(d.flash).not.toBeNull();
    expect(d.risingwave_connected).toBe(false);
  });

  it("opens a regression probe by its id even though the list leaves it out", async () => {
    const d = await traceDetail("5f962065-4446-4d13-8142-562d8e2d4a72");
    expect(d.found).toBe(true);
    expect(d.answer).toBe("Total net sales were $391,035 million.");
    expect(d.citations).toEqual([
      { chunk_id: "chunk-1", quote: "$391,035 million" },
    ]);
    // Three verdict rows exist for this trace. The oldest is partial, and the newest wins.
    expect(d.judge_state).toBe("evaluated");
    expect(d.flash).toMatchObject({
      timestamp_utc: "2026-10-08T00:20:53.595093Z",
      faithfulness_status: "complete",
      faithfulness_score: 1,
    });
  });

  it("says a trace is not found and does not invent one", async () => {
    const d = await traceDetail("00000000-0000-0000-0000-000000000000");
    expect(d.found).toBe(false);
    expect(d.query).toBeNull();
    expect(d.flash).toBeNull();
    expect(d.frontier.sampled).toBe(false);
  });
});

describe("metricsSnapshot", () => {
  const NOW = Date.parse("2026-10-23T12:00:00Z");

  it("rebuilds the newest one-minute throughput bucket from the archived requests", async () => {
    const s = await metricsSnapshot(NOW);
    expect(s.throughput).toMatchObject({
      total_requests: 3,
      success_count: 0,
      blocked_count: 2,
      error_count: 1,
      avg_latency_ms: 15015.7,
      p95_latency_ms: 21553.2,
      window_start: "2026-10-22T20:00:00Z",
      window_end: "2026-10-22T20:01:00Z",
    });
  });

  it("rebuilds the flash judge, usage and frontier sections with their original windows", async () => {
    const s = await metricsSnapshot(NOW);
    expect(s.faithfulness).toMatchObject({
      verdicts_count: 1,
      avg_faithfulness: 1,
      complete_count: 1,
      skipped_count: 0,
      window_end: "2026-10-22T20:00:00Z",
    });
    expect(s.relevance).toMatchObject({
      verdicts_count: 1,
      avg_answer_relevance: 1,
      avg_context_relevance: 0.56,
    });
    expect(s.tokens).toMatchObject({
      gemini_calls_total: 0,
      cost_total_usd: 0,
    });
    expect(s.cost?.cost_total_usd).toBe(0);
    expect(s.frontier).toEqual({
      window_minutes: 15,
      verdict_counts: { ensemble_supported: 1, ensemble_insufficient: 3 },
      disagreement_counts: { agree_supported: 1, all_unavailable: 3 },
      latest_window_end: "2026-10-21T19:37:00Z",
      stale: true,
    });
  });

  it("reports every section stale, because the archive is not current", async () => {
    const s = await metricsSnapshot(NOW);
    for (const section of [
      s.throughput,
      s.faithfulness,
      s.relevance,
      s.tokens,
      s.cost,
    ]) {
      expect(section?.stale).toBe(true);
    }
  });

  it("would read a bucket as fresh only within two minutes of its end", async () => {
    const fresh = await metricsSnapshot(Date.parse("2026-10-22T20:02:30Z"));
    expect(fresh.throughput?.stale).toBe(false);
    const old = await metricsSnapshot(Date.parse("2026-10-22T20:03:30Z"));
    expect(old.throughput?.stale).toBe(true);
  });
});

describe("calibrationHealth", () => {
  it("reads the committed canary reading and places it between the two thresholds", async () => {
    const c = await calibrationHealth();
    expect(c).toMatchObject({
      judge_id: "gemini-rubric",
      kappa: 0.5161290322580646,
      state: "degraded",
      window_n: 30,
      min_n: 30,
      drift_entry_threshold: 0.43,
      recovery_threshold: 0.54,
      position: "between_thresholds",
    });
    expect(c.state_as_of).toMatch(/^2026-10-04T17:/);
  });
});
