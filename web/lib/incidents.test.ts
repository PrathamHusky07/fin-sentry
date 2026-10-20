import { describe, expect, it } from "vitest";
import {
  budgetRows,
  evidenceRows,
  hypothesisRows,
  queryOutcome,
  recordHref,
  spendNote,
  timelineSteps,
  whyItRanks,
  type Assessed,
  type Detail,
  type HypothesisAssessment,
  type PredictionResult,
  type QueryRun,
  type TimelineEntry,
  type Usage,
} from "@/lib/incidents";

const prediction = (
  state: PredictionResult["state"],
  query_ids: string[] = ["q1"],
): PredictionResult => ({
  tool: "get_failing_traces",
  signal: "block_cluster",
  expect: true,
  subject: null,
  description: "blocks cluster",
  state,
  detail: "6 of 6 blocked",
  query_ids,
  restates_trigger: false,
});

const assessment = (
  id: string,
  status: HypothesisAssessment["status"],
  predictions: PredictionResult[],
  supporting: { kind: string; record_id: string }[] = [],
  contradicting: { kind: string; record_id: string }[] = [],
): HypothesisAssessment => ({
  hypothesis_id: id,
  subsystem: "judges",
  symptom: "s",
  statement: `statement ${id}`,
  status,
  supporting,
  contradicting,
  predictions,
  set_aside: [],
});

const entry = (seq: number, event: TimelineEntry["event"]): TimelineEntry => ({
  seq,
  at: "2026-10-01T12:00:00Z",
  elapsed_s: seq,
  event,
});

const query = (over: Partial<QueryRun> = {}): QueryRun => ({
  kind: "query",
  query_id: "q1",
  tool: "get_failing_traces",
  args: {},
  status: "ok",
  error: null,
  separates: [],
  retry_justification: null,
  empty_unverified: false,
  elapsed_s: 0.1,
  records: { "trace:t1": { block_rail: "faithfulness" } },
  ...over,
});

const base: Detail = {
  investigation_id: "i1",
  incident_id: "inc-i1",
  status: "completed",
  outcome: "diagnosis",
  origin: "live",
  planner: "gemini-planner:x",
  created_at: "2026-10-01T12:00:00Z",
  finished_at: "2026-10-01T12:00:05Z",
  trigger: { kind: "drift_degradation", reference_id: null, description: "d" },
  scope: { endpoint: null, ticker: null, trace_ids: [] },
  window: { start: "2026-10-01T11:00:00Z", end: "2026-10-01T12:00:00Z" },
  stopping_reason: "sufficient_evidence",
  leading: null,
  hypotheses: 2,
  queries: 1,
  model_calls: 1,
  cost_usd: 0.01,
  error: null,
  stale: false,
  heartbeat_at: "2026-10-01T12:00:05Z",
  timeline: [],
  state: null,
  report: null,
  usage: null,
};

describe("queryOutcome", () => {
  it("keeps the four non-answers apart from each other and from a result", () => {
    const outcomes = [
      queryOutcome({ status: "ok", empty_unverified: false }),
      queryOutcome({ status: "empty", empty_unverified: false }),
      queryOutcome({ status: "empty", empty_unverified: true }),
      queryOutcome({ status: "unavailable", empty_unverified: false }),
      queryOutcome({ status: "rejected", empty_unverified: false }),
    ];
    expect(outcomes).toEqual([
      "returned",
      "verified_empty",
      "unverified_empty",
      "unavailable",
      "rejected",
    ]);
    expect(new Set(outcomes).size).toBe(5);
  });
});

describe("recordHref", () => {
  it("links a live record to the page that shows it", () => {
    expect(recordHref({ kind: "trace", record_id: "t 1" }, "live")).toBe(
      "/investigations?trace=t%201",
    );
    expect(
      recordHref({ kind: "red_team_execution", record_id: "e1" }, "live"),
    ).toBe("/red-team?execution=e1");
  });
  it("links nothing for a fixture record or a record with no page", () => {
    expect(
      recordHref({ kind: "trace", record_id: "t1" }, "fixture"),
    ).toBeNull();
    expect(
      recordHref({ kind: "drift_report", record_id: "gemini-rubric" }, "live"),
    ).toBeNull();
  });
});

describe("whyItRanks", () => {
  it("says a leader met everything and had no supported rival", () => {
    const h = assessment("h1", "supported", [
      prediction("met"),
      prediction("met"),
    ]);
    expect(whyItRanks(h, true)).toMatch(/2 of 2 predictions met, none unmet/);
  });
  it("counts the records behind a refutation", () => {
    const h = assessment(
      "h2",
      "refuted",
      [prediction("unmet")],
      [],
      [
        { kind: "trace", record_id: "a" },
        { kind: "trace", record_id: "b" },
      ],
    );
    expect(whyItRanks(h, false)).toMatch(
      /0 of 1 prediction met. 2 records show/,
    );
  });
  it("does not call an open hypothesis likely, and says what stopped it", () => {
    const unchecked = assessment("h3", "open", [
      prediction("met"),
      prediction("unknown"),
    ]);
    expect(whyItRanks(unchecked, false)).toMatch(
      /1 prediction could not be checked/,
    );
    const noRecord = assessment("h4", "open", [prediction("unmet")]);
    expect(whyItRanks(noRecord, false)).toMatch(
      /failed with no record behind it/,
    );
  });
  it("admits when nothing could be checked", () => {
    expect(whyItRanks(assessment("h5", "open", []), false)).toMatch(
      /No prediction/,
    );
  });
});

describe("hypothesisRows", () => {
  const assessed: Assessed = {
    kind: "assessment",
    round: 1,
    decision: "diagnose",
    hypotheses: [
      assessment("h1", "refuted", [prediction("unmet")]),
      assessment(
        "h2",
        "supported",
        [prediction("met")],
        [{ kind: "trace", record_id: "t1" }],
      ),
    ],
    leaders: ["h2"],
    confidence: { h2: "medium" },
    notes: [],
    unresolved: [],
  };

  it("orders by the report's rank and marks the leader", () => {
    const detail: Detail = {
      ...base,
      timeline: [entry(1, assessed)],
      report: {
        incident_id: "inc-i1",
        outcome: "diagnosis",
        ranked_hypotheses: [
          {
            hypothesis_id: "h1",
            rank: 2,
            subsystem: "judges",
            statement: "a",
            confidence: "low",
            supporting: [],
            contradicting: [],
          },
          {
            hypothesis_id: "h2",
            rank: 1,
            subsystem: "judges",
            statement: "b",
            confidence: "medium",
            supporting: [],
            contradicting: [],
          },
        ],
        observations: [],
        correlations: [],
        causal_claims: [],
        missing_evidence: [],
        evidence_against: [],
        tool_unavailable: [],
        empty_results: [],
        tests_actually_run: [],
        proposed_verification: {
          kind: "none_available",
          scenario_id: null,
          tool: null,
          args: null,
          rationale: "r",
          executed: false,
        },
        limitations: [],
        stopping_reason: "sufficient_evidence",
        abstention_statement: null,
      },
    };
    const rows = hypothesisRows(detail);
    expect(rows.map((r) => [r.hypothesis_id, r.rank, r.leading])).toEqual([
      ["h2", 1, true],
      ["h1", 2, false],
    ]);
  });

  it("shows the last assessment unranked when no report was produced", () => {
    const rows = hypothesisRows({
      ...base,
      status: "failed",
      outcome: null,
      timeline: [entry(1, assessed)],
    });
    expect(rows.every((r) => r.rank === null && r.confidence === null)).toBe(
      true,
    );
    expect(rows).toHaveLength(2);
  });

  it("shows nothing when the investigator never assessed anything", () => {
    expect(
      hypothesisRows({
        ...base,
        status: "interrupted",
        timeline: [entry(1, query())],
      }),
    ).toEqual([]);
  });
});

describe("evidenceRows", () => {
  it("lists each cited record once with every role, and the query that returned it", () => {
    const detail: Detail = {
      ...base,
      timeline: [entry(1, query())],
      report: {
        incident_id: "inc-i1",
        outcome: "diagnosis",
        ranked_hypotheses: [
          {
            hypothesis_id: "h1",
            rank: 1,
            subsystem: "judges",
            statement: "a",
            confidence: "low",
            supporting: [
              { kind: "trace", record_id: "t1" },
              { kind: "query_result", record_id: "q1" },
            ],
            contradicting: [],
          },
        ],
        observations: [
          { statement: "o", evidence: [{ kind: "trace", record_id: "t1" }] },
        ],
        correlations: [],
        causal_claims: [],
        missing_evidence: [],
        evidence_against: [],
        tool_unavailable: [],
        empty_results: [],
        tests_actually_run: [],
        proposed_verification: {
          kind: "none_available",
          scenario_id: null,
          tool: null,
          args: null,
          rationale: "r",
          executed: false,
        },
        limitations: [],
        stopping_reason: "sufficient_evidence",
        abstention_statement: null,
      },
    };
    const rows = evidenceRows(detail);
    expect(rows).toHaveLength(1);
    expect(rows[0].roles).toEqual([
      "supports the leader",
      "cited in an observation",
    ]);
    expect(rows[0].queryIds).toEqual(["q1"]);
    expect(rows[0].facts).toEqual({ block_rail: "faithfulness" });
  });

  it("is empty without a report", () => {
    expect(evidenceRows(base)).toEqual([]);
  });
});

describe("timelineSteps", () => {
  it("reports how each hypothesis moved between assessments", () => {
    const first: Assessed = {
      kind: "assessment",
      round: 1,
      decision: "continue",
      hypotheses: [assessment("h1", "open", []), assessment("h2", "open", [])],
      leaders: [],
      confidence: {},
      notes: [],
      unresolved: ["x"],
    };
    const second: Assessed = {
      ...first,
      round: 2,
      decision: "diagnose",
      leaders: ["h1"],
      hypotheses: [
        assessment("h1", "supported", []),
        assessment("h2", "open", []),
      ],
    };
    const steps = timelineSteps({
      ...base,
      timeline: [entry(1, first), entry(2, second)],
    });
    expect(
      steps[0].changes.map((c) => [c.hypothesis_id, c.from, c.to]),
    ).toEqual([
      ["h1", null, "open"],
      ["h2", null, "open"],
    ]);
    expect(
      steps[1].changes.map((c) => [c.hypothesis_id, c.from, c.to]),
    ).toEqual([["h1", "open", "supported"]]);
  });
});

describe("budget and spend", () => {
  const usage: Usage = {
    budgets: {
      max_tool_calls: 8,
      max_inference_calls: 2,
      max_hypothesis_rounds: 3,
      max_wall_clock_s: 120,
    },
    used: {
      tool_calls: 7,
      inference_calls: 1,
      hypothesis_rounds: 2,
      wall_clock_s: 3.456,
    },
    model: {
      planner: "p",
      calls: 1,
      unmetered_calls: 0,
      prompt_tokens: 1,
      candidates_tokens: 1,
      thought_tokens: 1,
      cost_usd: 0.01,
      call_log: [],
    },
  };
  it("pairs each ceiling with what was used", () => {
    expect(
      budgetRows(usage).map((r) => `${r.label} ${r.used}/${r.max}`),
    ).toEqual([
      "Tool calls 7/8",
      "Model calls 1/2",
      "Hypothesis rounds 2/3",
      "Wall clock 3.5/120",
    ]);
  });
  it("leaves the wall clock out of a fixture replay, which runs on a stubbed clock", () => {
    expect(budgetRows(usage, "fixture").map((r) => r.label)).not.toContain(
      "Wall clock",
    );
    expect(budgetRows(usage, "live").map((r) => r.label)).toContain(
      "Wall clock",
    );
  });
  it("says a fixture called no model and a live figure is an estimate", () => {
    expect(spendNote(usage, "fixture")).toMatch(/No model was called/);
    expect(spendNote(usage, "live")).toMatch(/estimate, not a bill/);
    expect(
      spendNote(
        { ...usage, model: { ...usage.model, unmetered_calls: 2 } },
        "live",
      ),
    ).toMatch(/2 calls returned no usage/);
  });
});
