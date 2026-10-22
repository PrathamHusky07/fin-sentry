import { describe, expect, it } from "vitest";
import {
  ACTOR_LABEL,
  LINKS,
  MAP,
  STAGES,
  citationTrace,
  defaultHypothesis,
  linkState,
  missingFor,
  nodeState,
  queryTally,
  relatedStages,
  rivalsOf,
  stagePosition,
  stepStage,
  stoppedWhy,
} from "@/lib/agent-view";
import type {
  Detail,
  HypothesisRow,
  PredictionResult,
  QueryRun,
  TimelineEntry,
} from "@/lib/incidents";

const prediction = (state: PredictionResult["state"]): PredictionResult => ({
  tool: "get_failing_traces",
  signal: "block_cluster",
  expect: true,
  subject: null,
  description: `a ${state} prediction`,
  state,
  detail: "d",
  query_ids: ["q1"],
  restates_trigger: false,
});

const row = (
  id: string,
  symptom: string | null,
  leading = false,
  predictions: PredictionResult[] = [],
): HypothesisRow => ({
  hypothesis_id: id,
  rank: leading ? 1 : null,
  symptom,
  subsystem: "judges",
  statement: id,
  status: "open",
  confidence: null,
  supporting: [],
  contradicting: [],
  predictions,
  set_aside: [],
  why: "",
  leading,
});

const query = (
  id: string,
  status: QueryRun["status"],
  records: QueryRun["records"] = {},
  empty_unverified = false,
): QueryRun => ({
  kind: "query",
  query_id: id,
  tool: "search_traces",
  args: {},
  status,
  error: null,
  separates: [],
  retry_justification: null,
  empty_unverified,
  elapsed_s: 0.1,
  records,
});

const entry = (seq: number, event: TimelineEntry["event"]): TimelineEntry => ({
  seq,
  at: "2026-10-01T12:00:00Z",
  elapsed_s: seq,
  event,
});

const base = {
  investigation_id: "i1",
  incident_id: "inc-i1",
  status: "completed",
  outcome: "diagnosis",
  origin: "fixture",
  planner: "planner-double",
  created_at: "2026-10-01T12:00:00Z",
  finished_at: "2026-10-01T12:00:05Z",
  trigger: { kind: "single_trace", reference_id: "t1", description: "d" },
  scope: { endpoint: null, ticker: null, trace_ids: [] },
  window: { start: "2026-10-01T11:00:00Z", end: "2026-10-01T12:00:00Z" },
  stopping_reason: "sufficient_evidence",
  leading: null,
  hypotheses: 2,
  queries: 2,
  model_calls: 0,
  cost_usd: 0,
  error: null,
  stale: false,
  heartbeat_at: "2026-10-01T12:00:05Z",
  timeline: [],
  state: null,
  report: null,
  usage: null,
} satisfies Detail;

describe("the mechanism map", () => {
  it("has six stages in order and exactly one that calls a model", () => {
    expect(STAGES.map((s) => s.id)).toEqual([
      "trigger",
      "plan",
      "execute",
      "assess",
      "validate",
      "conclude",
    ]);
    expect(STAGES.filter((s) => s.actor === "model").map((s) => s.id)).toEqual([
      "plan",
    ]);
    expect(ACTOR_LABEL.model).toBe("Model proposes");
  });

  it("connects the incident to every stage, each stage to the next, and the re-plan loop", () => {
    expect(LINKS.filter((l) => l.kind === "spoke")).toHaveLength(6);
    expect(LINKS.filter((l) => l.kind === "sequence")).toHaveLength(5);
    expect(LINKS.filter((l) => l.kind === "loop")).toEqual([
      expect.objectContaining({ from: "assess", to: "plan" }),
    ]);
  });

  it("brings the selected stage forward, keeps its connections lit and quiets the rest", () => {
    expect(relatedStages("assess").sort()).toEqual(
      ["execute", "plan", "validate"].sort(),
    );
    expect(nodeState("assess", "assess")).toBe("active");
    expect(nodeState("plan", "assess")).toBe("related");
    expect(nodeState("conclude", "assess")).toBe("dim");
    expect(nodeState("incident", "assess")).toBe("related");
    const states = Object.fromEntries(
      LINKS.map((l) => [l.id, linkState(l, "assess")]),
    );
    expect(states["spoke-assess"]).toBe("lit");
    expect(states["seq-execute-assess"]).toBe("lit");
    expect(states["loop"]).toBe("lit");
    expect(states["spoke-trigger"]).toBe("dim");
    expect(states["seq-trigger-plan"]).toBe("dim");
  });

  it("draws everything at rest when nothing is selected", () => {
    expect(nodeState("plan", null)).toBe("rest");
    expect(LINKS.every((l) => linkState(l, null) === "rest")).toBe(true);
  });

  it("steps through the stages and wraps at both ends", () => {
    expect(stepStage("trigger", 1)).toBe("plan");
    expect(stepStage("conclude", 1)).toBe("trigger");
    expect(stepStage("trigger", -1)).toBe("conclude");
  });

  it("keeps the nodes inside the drawing and apart from each other", () => {
    const xs = STAGES.map((_, i) => stagePosition(i));
    for (const p of xs) {
      expect(p.x - MAP.nodeW / 2).toBeGreaterThanOrEqual(0);
      expect(p.x + MAP.nodeW / 2).toBeLessThanOrEqual(MAP.width);
      expect(p.y - MAP.nodeH / 2).toBeGreaterThan(0);
      expect(p.y + MAP.nodeH / 2).toBeLessThan(MAP.incident.y - MAP.incident.r);
      expect(MAP.incident.y + MAP.incident.r).toBeLessThanOrEqual(MAP.height);
      expect(MAP.incident.x - MAP.incident.r).toBeGreaterThanOrEqual(0);
    }
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i].x - xs[i - 1].x).toBeGreaterThan(MAP.nodeW);
    }
  });
});

describe("rivals and missing evidence", () => {
  const rows = [
    row("h1", "s1", true),
    row("h2", "s1"),
    row("h3", "s2"),
    row("h4", null),
  ];

  it("treats hypotheses for the same symptom as rivals and nothing else", () => {
    expect(rivalsOf(rows, "h1").map((r) => r.hypothesis_id)).toEqual(["h2"]);
    expect(rivalsOf(rows, "h3")).toEqual([]);
    expect(rivalsOf(rows, "h4")).toEqual([]);
    expect(rivalsOf(rows, "missing")).toEqual([]);
  });

  it("opens on the leader, else the first row, else nothing", () => {
    expect(defaultHypothesis(rows)).toBe("h1");
    expect(defaultHypothesis([row("a", null), row("b", null)])).toBe("a");
    expect(defaultHypothesis([])).toBeNull();
  });

  it("lists unchecked and absent predictions and never a met one", () => {
    const r = row("h1", "s1", true, [
      prediction("met"),
      prediction("unknown"),
      prediction("unmet"),
    ]);
    expect(missingFor(r).map((m) => m.kind)).toEqual(["unchecked", "absent"]);
  });
});

describe("queryTally", () => {
  it("counts each of the five result states separately", () => {
    const detail: Detail = {
      ...base,
      timeline: [
        entry(1, query("q1", "ok", { "trace:a": {} })),
        entry(2, query("q2", "empty")),
        entry(3, query("q3", "empty", {}, true)),
        entry(4, query("q4", "unavailable")),
        entry(5, query("q5", "rejected")),
        entry(6, query("q6", "ok", { "trace:b": {} })),
      ],
    };
    expect(queryTally(detail)).toEqual({
      returned: 2,
      verified_empty: 1,
      unverified_empty: 1,
      unavailable: 1,
      rejected: 1,
    });
  });
});

describe("citationTrace", () => {
  const report: NonNullable<Detail["report"]> = {
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
          { kind: "trace", record_id: "a" },
          { kind: "trace", record_id: "ghost" },
        ],
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
      rationale: "",
      executed: false,
    },
    limitations: [],
    stopping_reason: "sufficient_evidence",
    abstention_statement: null,
  };

  it("is null when no report was stored", () => {
    expect(citationTrace(base)).toBeNull();
  });

  it("separates a cited record a query returned from one no stored query returned", () => {
    const trace = citationTrace({
      ...base,
      timeline: [entry(1, query("q1", "ok", { "trace:a": {} }))],
      report,
    });
    expect(trace).toEqual({
      cited: 2,
      traced: 1,
      untraced: [{ kind: "trace", record_id: "ghost" }],
    });
  });
});

describe("stoppedWhy", () => {
  it("reads the recorded reason, and is null before a stop", () => {
    expect(stoppedWhy(base)).toBeNull();
    expect(
      stoppedWhy({
        ...base,
        timeline: [
          entry(1, {
            kind: "stopped",
            stopping_reason: "justified_abstention",
            outcome: "abstention",
            why: "the records did not support a cause",
          }),
        ],
      }),
    ).toBe("the records did not support a cause");
  });
});
