import { describe, expect, it } from "vitest";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  OUTCOMES,
  OUTCOME_LABEL,
  evaluatorStatus,
  expectationLabel,
  expectedLabel,
  groupByCategory,
  isDetection,
  runProgress,
  sentGatewayRequest,
  summarizeLatest,
  traceHref,
  type ExecutionRecord,
  type Expected,
  type Outcome,
  type RunRecord,
  type ScenarioView,
} from "@/lib/red-team";

const CAUGHT_BY_PG: Expected = {
  outcome: "caught",
  layer: "prompt-guard-2",
  check: null,
  known_gap: false,
  rationale: "r",
};
const KNOWN_GAP: Expected = {
  outcome: "missed",
  layer: null,
  check: null,
  known_gap: true,
  rationale: "r",
};

function execution(overrides: Partial<ExecutionRecord> = {}): ExecutionRecord {
  return {
    execution_id: "e1",
    run_id: "r1",
    seq: 0,
    scenario_id: "DI-001",
    scenario_version: 1,
    category: "direct_injection",
    target_layer: "prompt-guard-2",
    mode: "deterministic",
    expected: CAUGHT_BY_PG,
    state: "finished",
    outcome: "caught",
    acting_layer: "prompt-guard-2",
    acting_check: null,
    expectation: "met",
    reason: "Blocked.",
    evidence: {},
    trace_ref: null,
    gemini_calls: 0,
    cost_usd: 0,
    started_at: "2026-10-08T20:00:00Z",
    finished_at: "2026-10-08T20:00:01Z",
    duration_ms: 1000,
    ...overrides,
  };
}

function scenario(
  id: string,
  category: ScenarioView["category"],
  last: ExecutionRecord | null,
): ScenarioView {
  return {
    id,
    version: 1,
    title: id,
    category,
    target_layer: "prompt-guard-2",
    description: "d",
    executor: "gateway_route",
    mode: "deterministic",
    expected: CAUGHT_BY_PG,
    required_evidence: [],
    severity: "high",
    severity_rationale: "s",
    input: {},
    last_execution: last,
  };
}

describe("isDetection", () => {
  it("is true only for caught, never for a failed or unavailable evaluator", () => {
    const detections = OUTCOMES.filter((o) => isDetection(o));
    expect(detections).toEqual(["caught"]);
    expect(isDetection("evaluator_unavailable")).toBe(false);
    expect(isDetection("execution_failed")).toBe(false);
    expect(isDetection("inconclusive")).toBe(false);
    expect(isDetection("missed")).toBe(false);
    expect(isDetection(null)).toBe(false);
  });

  it("gives every outcome its own distinct label", () => {
    const labels = OUTCOMES.map((o) => OUTCOME_LABEL[o]);
    expect(new Set(labels).size).toBe(OUTCOMES.length);
    expect(labels).not.toContain("Passed");
    expect(labels).not.toContain("Success");
  });
});

describe("summarizeLatest", () => {
  it("counts scenarios by their latest outcome and keeps never-run ones apart", () => {
    const summary = summarizeLatest([
      scenario("A-001", "direct_injection", execution()),
      scenario(
        "A-002",
        "direct_injection",
        execution({ outcome: "missed", expectation: "not_met" }),
      ),
      scenario(
        "A-003",
        "pii",
        execution({
          outcome: "evaluator_unavailable",
          expectation: "not_assessable",
        }),
      ),
      scenario(
        "A-004",
        "pii",
        execution({
          outcome: "execution_failed",
          expectation: "not_assessable",
        }),
      ),
      scenario("A-005", "pii", null),
    ]);
    expect(summary.counts).toEqual({
      caught: 1,
      missed: 1,
      evaluator_unavailable: 1,
      execution_failed: 1,
      inconclusive: 0,
    });
    expect(summary.notRun).toBe(1);
    expect(summary.differs).toBe(1);
    expect(summary.scenarioCount).toBe(5);
  });

  it("never counts an unavailable or failed result as caught", () => {
    const summary = summarizeLatest([
      scenario("A-001", "pii", execution({ outcome: "evaluator_unavailable" })),
      scenario("A-002", "pii", execution({ outcome: "execution_failed" })),
    ]);
    expect(summary.counts.caught).toBe(0);
  });

  it("counts confirmed known gaps separately from unexpected misses", () => {
    const summary = summarizeLatest([
      scenario(
        "GAP-001",
        "citation_integrity",
        execution({
          outcome: "missed",
          expectation: "met",
          expected: KNOWN_GAP,
        }),
      ),
    ]);
    expect(summary.gapsConfirmed).toBe(1);
    expect(summary.differs).toBe(0);
  });

  it("treats an empty registry as nothing run, not as healthy", () => {
    const summary = summarizeLatest([]);
    expect(summary.scenarioCount).toBe(0);
    expect(Object.values(summary.counts).every((n) => n === 0)).toBe(true);
  });

  it("uses a single execution per scenario even after many reruns", () => {
    const summary = summarizeLatest([
      scenario("A-001", "pii", execution({ outcome: "missed" })),
    ]);
    expect(summary.counts.missed).toBe(1);
    expect(summary.counts.caught).toBe(0);
  });
});

describe("expectation wording", () => {
  it("names the expected layer and the known gap", () => {
    expect(expectedLabel(CAUGHT_BY_PG)).toBe("Caught by Prompt Guard 2");
    expect(expectedLabel({ ...CAUGHT_BY_PG, check: "prompt-guard" })).toBe(
      "Caught by Prompt Guard 2, prompt-guard check",
    );
    expect(expectedLabel(KNOWN_GAP)).toBe("Missed (known gap)");
  });

  it("labels each relation between expected and observed distinctly", () => {
    expect(expectationLabel(execution())).toBe("Matches expectation");
    expect(
      expectationLabel(
        execution({
          outcome: "missed",
          expectation: "met",
          expected: KNOWN_GAP,
        }),
      ),
    ).toBe("Known gap confirmed");
    expect(expectationLabel(execution({ expectation: "not_met" }))).toBe(
      "Differs from expectation",
    );
    expect(
      expectationLabel(
        execution({
          outcome: "evaluator_unavailable",
          expectation: "not_assessable",
        }),
      ),
    ).toBe("Not assessable");
    expect(
      expectationLabel(
        execution({ state: "running", outcome: null, expectation: null }),
      ),
    ).toBe("Pending");
  });
});

describe("evaluatorStatus", () => {
  it("separates a rail that could not run from a harness that never reached it", () => {
    const status = (outcome: Outcome | null, state = "finished") =>
      evaluatorStatus(
        execution({ outcome, state: state as ExecutionRecord["state"] }),
      );
    expect(status("caught")).toBe("available");
    expect(status("missed")).toBe("available");
    expect(status("inconclusive")).toBe("available");
    expect(status("evaluator_unavailable")).toBe("unavailable");
    expect(status("execution_failed")).toBe("not_reached");
    expect(status(null, "running")).toBe("pending");
  });
});

describe("trace and request provenance", () => {
  it("links only to a stored trace and only gateway requests have one", () => {
    expect(traceHref("abc 1")).toBe("/investigations?trace=abc%201");
    expect(
      sentGatewayRequest(execution({ evidence: { gateway_status: 403 } })),
    ).toBe(true);
    expect(
      sentGatewayRequest(execution({ evidence: { rail_status: "x" } })),
    ).toBe(false);
  });
});

describe("runProgress", () => {
  const run: RunRecord = {
    run_id: "r1",
    created_at: "2026-10-08T20:00:00Z",
    finished_at: null,
    status: "running",
    scenario_ids: ["A", "B", "C"],
    allow_judge_assisted: false,
    failure_reason: null,
    total: 3,
    finished: 1,
    outcome_counts: { caught: 1 },
  };

  it("reports finished over total and never divides by zero", () => {
    expect(runProgress(run)).toEqual({ finished: 1, total: 3, percent: 33 });
    expect(runProgress({ ...run, total: 0, finished: 0 }).percent).toBe(0);
  });
});

describe("groupByCategory", () => {
  it("orders groups by the path a request travels and omits empty ones", () => {
    const groups = groupByCategory([
      scenario("O-001", "output_schema", null),
      scenario("D-001", "direct_injection", null),
      scenario("D-002", "direct_injection", null),
    ]);
    expect(groups.map((g) => g.category)).toEqual([
      "direct_injection",
      "output_schema",
    ]);
    expect(groups[0].scenarios.map((s) => s.id)).toEqual(["D-001", "D-002"]);
  });

  it("labels every category it can order", () => {
    for (const c of CATEGORY_ORDER) expect(CATEGORY_LABEL[c]).toBeTruthy();
  });
});
