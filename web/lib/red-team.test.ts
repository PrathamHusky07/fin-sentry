import { describe, expect, it } from "vitest";
import {
  ATTENTION_LABEL,
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CONTINUATION_LABEL,
  CONTINUATION_MEANING,
  OUTCOMES,
  OUTCOME_LABEL,
  SAFETY_BOUND_LABEL,
  SAFETY_BOUND_MEANING,
  NO_EXPLORER_FILTERS,
  attentionItems,
  byScenario,
  canInvestigate,
  changeBetween,
  continuationState,
  countExecutions,
  evaluatorStatus,
  filterScenarios,
  findingHeadline,
  groupByLayer,
  historySummary,
  resolveDetail,
  streakChanges,
  streaks,
  expectationLabel,
  expectedLabel,
  groupByCategory,
  isDetection,
  gatewayProvenanceUnrecorded,
  isSafetyBoundSkip,
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

describe("gateway continuation", () => {
  it("reads three honest states and treats unknown as its own, never as stopped", () => {
    const state = (evidence: Record<string, unknown>) =>
      continuationState(execution({ evidence }));
    expect(state({ continued_past_input_rails: true })).toBe("continued");
    expect(state({ continued_past_input_rails: false })).toBe("stopped");
    expect(state({ continuation_unknown: true })).toBe("unknown");
    expect(state({})).toBe("not_recorded");
    expect(state({ rail_status: "x" })).toBe("not_recorded");
  });

  it("never reports stopped when the continuation is unknown", () => {
    const e = execution({
      outcome: "execution_failed",
      evidence: { continuation_unknown: true },
    });
    expect(continuationState(e)).not.toBe("stopped");
    expect(continuationState(e)).not.toBe("not_recorded");
  });
});

describe("unknown continuation copy", () => {
  it("says the execution was interrupted and never asserts that a request was sent", () => {
    const meaning = CONTINUATION_MEANING.unknown;
    expect(meaning).toContain("interrupted");
    expect(meaning).toContain("unknown");
    expect(meaning).not.toMatch(/tried to send|failed before/i);
    expect(CONTINUATION_LABEL.unknown).toContain("unknown");
  });
});

describe("gateway provenance not recorded", () => {
  const unrecorded = (
    evidence: Record<string, unknown>,
    executor: string | null,
    over: Partial<ExecutionRecord> = {},
  ) => gatewayProvenanceUnrecorded(execution({ evidence, ...over }), executor);

  it("is true for a legacy gateway execution with no marker and no gateway response", () => {
    expect(unrecorded({}, "gateway_route")).toBe(true);
  });

  it("is also true when the scenario's executor cannot be resolved", () => {
    expect(unrecorded({}, null)).toBe(true);
  });

  it("is false for an execution that does not use the gateway", () => {
    expect(unrecorded({}, "output_rails")).toBe(false);
    expect(unrecorded({}, "input_rails")).toBe(false);
  });

  it("is false whenever the record carries gateway evidence", () => {
    expect(unrecorded({ gateway_status: 200 }, "gateway_route")).toBe(false);
    expect(unrecorded({ continuation_unknown: true }, "gateway_route")).toBe(
      false,
    );
    expect(
      unrecorded({ continued_past_input_rails: false }, "gateway_route"),
    ).toBe(false);
  });

  it("is false for a safety-bound skip, which has its own copy", () => {
    expect(
      unrecorded({ skipped_by_safety_bound: true }, "gateway_route", {
        outcome: "execution_failed",
      }),
    ).toBe(false);
  });
});

describe("safety-bound skip", () => {
  const skipped = execution({
    outcome: "execution_failed",
    expectation: "not_assessable",
    evidence: { skipped_by_safety_bound: true },
  });
  const harnessFailure = execution({
    outcome: "execution_failed",
    expectation: "not_assessable",
    evidence: {},
  });

  it("is told apart from a harness failure by the structured marker", () => {
    expect(isSafetyBoundSkip(skipped)).toBe(true);
    expect(isSafetyBoundSkip(harnessFailure)).toBe(false);
    expect(
      isSafetyBoundSkip(
        execution({
          outcome: "execution_failed",
          evidence: { continuation_unknown: true },
        }),
      ),
    ).toBe(false);
  });

  it("applies only to execution_failed, so no other outcome can be relabelled", () => {
    for (const o of OUTCOMES.filter((o) => o !== "execution_failed")) {
      expect(
        isSafetyBoundSkip(
          execution({
            outcome: o,
            evidence: { skipped_by_safety_bound: true },
          }),
        ),
      ).toBe(false);
    }
  });

  it("keeps the persisted outcome in the counts and reports the skips beside them", () => {
    const summary = summarizeLatest([
      scenario("A-001", "direct_injection", skipped),
      scenario("A-002", "direct_injection", harnessFailure),
    ]);
    expect(summary.counts.execution_failed).toBe(2);
    expect(summary.safetyBoundSkips).toBe(1);
  });

  it("describes a deliberate skip, not a harness failure or a direct defense call", () => {
    expect(SAFETY_BOUND_LABEL).toBe("Not run (safety bound)");
    expect(SAFETY_BOUND_MEANING).toMatch(/intentionally skipped to bound cost/);
    expect(SAFETY_BOUND_MEANING).not.toMatch(/harness itself failed/);
    expect(SAFETY_BOUND_MEANING).not.toMatch(/called the defense directly/);
  });
});

describe("groupByLayer", () => {
  it("orders lanes along the path of a request and omits empty ones", () => {
    const lane = (id: string, layer: string) => ({
      ...scenario(id, "pii", null),
      target_layer: layer,
    });
    const lanes = groupByLayer([
      lane("O-002", "faithfulness"),
      lane("I-001", "prompt-guard-2"),
      lane("R-001", "retrieval-rail"),
      lane("I-002", "prompt-guard-2"),
    ]);
    expect(lanes.map((l) => [l.layer, l.stage])).toEqual([
      ["prompt-guard-2", "input"],
      ["retrieval-rail", "retrieval"],
      ["faithfulness", "output"],
    ]);
    expect(lanes[0].scenarios.map((s) => s.id)).toEqual(["I-001", "I-002"]);
  });

  it("keeps a layer the registry adds after the known ones, with no stage", () => {
    const lanes = groupByLayer([
      { ...scenario("N-001", "pii", null), target_layer: "new-rail" },
      scenario("D-001", "direct_injection", null),
    ]);
    expect(lanes.map((l) => l.layer)).toEqual(["prompt-guard-2", "new-rail"]);
    expect(lanes[1].stage).toBeNull();
  });
});

describe("filterScenarios", () => {
  const scenarios = [
    scenario("A-001", "direct_injection", execution()),
    {
      ...scenario("A-002", "pii", execution({ outcome: "missed" })),
      severity: "critical" as const,
    },
    {
      ...scenario("A-003", "pii", null),
      mode: "judge_assisted" as const,
    },
  ];
  const ids = (f: Partial<typeof NO_EXPLORER_FILTERS>) =>
    filterScenarios(scenarios, { ...NO_EXPLORER_FILTERS, ...f }).map(
      (s) => s.id,
    );

  it("filters on real registry and result fields", () => {
    expect(ids({})).toEqual(["A-001", "A-002", "A-003"]);
    expect(ids({ result: "missed" })).toEqual(["A-002"]);
    expect(ids({ result: "not_run" })).toEqual(["A-003"]);
    expect(ids({ severity: "critical" })).toEqual(["A-002"]);
    expect(ids({ mode: "judge_assisted" })).toEqual(["A-003"]);
    expect(ids({ category: "pii", result: "missed" })).toEqual(["A-002"]);
  });
});

describe("history", () => {
  const at = (minute: number) => ({
    started_at: `2026-10-08T20:${String(minute).padStart(2, "0")}:00Z`,
    seq: minute,
    execution_id: `e${minute}`,
  });

  it("collapses identical re-runs into one streak and keeps every execution", () => {
    const runs = Array.from({ length: 14 }, (_, i) => execution(at(i)));
    const list = streaks(runs);
    expect(list).toHaveLength(1);
    expect(list[0].executions).toHaveLength(14);
    expect(list[0].first.execution_id).toBe("e0");
    expect(list[0].last.execution_id).toBe("e13");
  });

  it("orders by start time and not by the order the API returned them", () => {
    const grouped = byScenario([
      execution(at(5)),
      execution({ ...at(1), scenario_id: "DI-001" }),
      execution({ ...at(3), scenario_id: "OUT-001" }),
    ]);
    expect(grouped.get("DI-001")?.map((e) => e.execution_id)).toEqual([
      "e1",
      "e5",
    ]);
    expect(grouped.get("OUT-001")).toHaveLength(1);
  });

  it("starts a new streak when the version, outcome or expectation changes", () => {
    const list = streaks([
      execution(at(1)),
      execution(at(2)),
      execution({ ...at(3), scenario_version: 2 }),
      execution({ ...at(4), scenario_version: 2, outcome: "missed" }),
    ]);
    expect(list.map((s) => s.executions.length)).toEqual([2, 1, 1]);
  });

  it("reports a caught result that becomes a miss as a regression", () => {
    const caught = execution(at(1));
    const missed = execution({
      ...at(2),
      outcome: "missed",
      expectation: "not_met",
    });
    expect(changeBetween(caught, missed)).toBe("regression");
    expect(changeBetween(missed, caught)).toBe("recovery");
  });

  it("does not call a loss of evidence a miss", () => {
    const caught = execution(at(1));
    for (const outcome of [
      "evaluator_unavailable",
      "execution_failed",
      "inconclusive",
    ] as const) {
      expect(
        changeBetween(
          caught,
          execution({ ...at(2), outcome, expectation: "not_assessable" }),
        ),
      ).toBe("lost_result");
    }
  });

  it("reports an expectation that stopped matching and a new scenario version", () => {
    const met = execution(at(1));
    expect(
      changeBetween(met, execution({ ...at(2), expectation: "not_met" })),
    ).toBe("expectation_lost");
    expect(
      changeBetween(
        execution({ ...at(1), expectation: "not_met" }),
        execution({ ...at(2), scenario_version: 2 }),
      ),
    ).toBe("expectation_regained");
    expect(
      changeBetween(met, execution({ ...at(2), scenario_version: 2 })),
    ).toBe("new_version");
    expect(changeBetween(met, execution(at(2)))).toBeNull();
  });

  it("gives the change that led into each streak and none to the first", () => {
    const list = streaks([
      execution(at(1)),
      execution({ ...at(2), outcome: "missed", expectation: "not_met" }),
    ]);
    expect(streakChanges(list)).toEqual([null, "regression"]);
  });

  it("never reports a change across a running or queued execution", () => {
    expect(
      changeBetween(
        execution(at(1)),
        execution({ ...at(2), state: "running", outcome: null }),
      ),
    ).toBeNull();
  });
});

describe("attentionItems", () => {
  const gap = scenario(
    "GAP-001",
    "citation_integrity",
    execution({
      outcome: "missed",
      expectation: "met",
      expected: KNOWN_GAP,
      scenario_id: "GAP-001",
      execution_id: "g1",
      started_at: "2026-10-08T20:00:00Z",
    }),
  );
  const held = scenario("DI-001", "direct_injection", execution());
  const none = new Map<string, ExecutionRecord[]>();

  it("omits a scenario that was caught as expected and one never run", () => {
    expect(
      attentionItems([held, scenario("N-001", "pii", null)], none),
    ).toEqual([]);
  });

  it("lists a confirmed known gap as such and not as an unexpected miss", () => {
    const items = attentionItems([held, gap], none);
    expect(items.map((i) => [i.scenario.id, i.kind])).toEqual([
      ["GAP-001", "known_gap"],
    ]);
  });

  it("ranks a regression above an unexpected miss above a difference", () => {
    const earlier = execution({
      scenario_id: "R-001",
      execution_id: "r0",
      started_at: "2026-10-08T19:00:00Z",
    });
    const now = execution({
      scenario_id: "R-001",
      execution_id: "r1",
      started_at: "2026-10-08T20:00:00Z",
      outcome: "missed",
      expectation: "not_met",
    });
    const regressed = scenario("R-001", "pii", now);
    const missed = scenario(
      "M-001",
      "pii",
      execution({
        outcome: "missed",
        expectation: "not_met",
        execution_id: "m1",
      }),
    );
    const differs = scenario(
      "D-009",
      "pii",
      execution({ expectation: "not_met", execution_id: "d1" }),
    );
    const items = attentionItems(
      [differs, gap, missed, regressed],
      new Map([["R-001", [earlier, now]]]),
    );
    expect(items.map((i) => i.kind)).toEqual([
      "regression",
      "missed",
      "differs",
      "known_gap",
    ]);
    expect(items[0].change).toBe("regression");
  });

  it("lists evaluator outages, failures and skips as saying nothing, never as a miss", () => {
    const rows = (
      ["evaluator_unavailable", "execution_failed", "inconclusive"] as const
    ).map((outcome, i) =>
      scenario(
        `X-00${i}`,
        "pii",
        execution({
          outcome,
          expectation: "not_assessable",
          execution_id: `x${i}`,
        }),
      ),
    );
    const skip = scenario(
      "X-009",
      "pii",
      execution({
        outcome: "execution_failed",
        expectation: "not_assessable",
        evidence: { skipped_by_safety_bound: true },
        execution_id: "x9",
      }),
    );
    const kinds = attentionItems([...rows, skip], none).map((i) => i.kind);
    expect(kinds).toEqual(["unavailable", "failed", "inconclusive", "skipped"]);
    for (const k of kinds) expect(ATTENTION_LABEL[k]).not.toMatch(/^Caught$/);
  });

  it("breaks a tie by severity and then id", () => {
    const a = {
      ...scenario("B-001", "pii", execution({ expectation: "not_met" })),
      severity: "low" as const,
    };
    const b = {
      ...scenario(
        "A-001",
        "pii",
        execution({ expectation: "not_met", execution_id: "b" }),
      ),
      severity: "critical" as const,
    };
    expect(attentionItems([a, b], none).map((i) => i.scenario.id)).toEqual([
      "A-001",
      "B-001",
    ]);
  });
});

describe("canInvestigate", () => {
  it("is offered for a miss and a differing result, and for nothing that says nothing", () => {
    expect(canInvestigate(execution({ outcome: "missed" }))).toBe(true);
    expect(canInvestigate(execution({ expectation: "not_met" }))).toBe(true);
    expect(canInvestigate(execution())).toBe(false);
    for (const outcome of [
      "evaluator_unavailable",
      "execution_failed",
      "inconclusive",
    ] as const) {
      expect(
        canInvestigate(execution({ outcome, expectation: "not_assessable" })),
      ).toBe(false);
    }
    expect(canInvestigate(execution({ state: "running", outcome: null }))).toBe(
      false,
    );
  });
});

describe("countExecutions and the headline", () => {
  it("counts executions by outcome and leaves unfinished ones out", () => {
    const counts = countExecutions([
      execution(),
      execution(),
      execution({ outcome: "missed" }),
      execution({ outcome: null, state: "running" }),
    ]);
    expect(counts.caught).toBe(2);
    expect(counts.missed).toBe(1);
  });

  it("says a known gap is open and the rest held, never that all is well", () => {
    const gap = scenario(
      "GAP-001",
      "citation_integrity",
      execution({
        outcome: "missed",
        expectation: "met",
        expected: KNOWN_GAP,
        scenario_id: "GAP-001",
      }),
    );
    const scenarios = [
      scenario("DI-001", "direct_injection", execution()),
      gap,
    ];
    const items = attentionItems(scenarios, new Map());
    const text = findingHeadline(summarizeLatest(scenarios), items);
    expect(text).toContain("1 known gap remains open");
    expect(text).toContain("1 other scenario held as expected");
  });

  it("reports nothing run, an empty registry and an all-held registry plainly", () => {
    expect(findingHeadline(summarizeLatest([]), [])).toBe(
      "The scenario registry is empty.",
    );
    const unrun = [scenario("A-001", "pii", null)];
    expect(findingHeadline(summarizeLatest(unrun), [])).toMatch(
      /No scenario has been run/,
    );
    const held = [scenario("A-001", "pii", execution())];
    expect(findingHeadline(summarizeLatest(held), [])).toBe(
      "The one scenario with a result held as expected.",
    );
  });
});

describe("historySummary", () => {
  it("says all alike for a repeated result and counts the differences otherwise", () => {
    const run = (i: number, over: Partial<ExecutionRecord> = {}) =>
      execution({
        execution_id: `e${i}`,
        started_at: `2026-10-08T20:0${i}:00Z`,
        seq: i,
        ...over,
      });
    expect(historySummary([])).toBe("Not run");
    expect(historySummary(streaks([run(1)]))).toBe("1 execution, caught");
    expect(historySummary(streaks([run(1), run(2), run(3)]))).toBe(
      "3 executions, all caught",
    );
    expect(
      historySummary(
        streaks([
          run(1),
          run(2, { outcome: "missed", expectation: "not_met" }),
        ]),
      ),
    ).toBe("2 executions, 2 different results");
  });
});

describe("resolveDetail follows the filtered set", () => {
  const a: ScenarioView = {
    ...scenario("A-1", "direct_injection", null),
    severity: "critical",
  };
  const b: ScenarioView = {
    ...scenario("B-1", "direct_injection", null),
    severity: "low",
  };
  const all = [a, b];

  it("opens the selected scenario while it is visible", () => {
    expect(resolveDetail(all, all, "A-1")).toEqual({
      kind: "open",
      scenario: a,
    });
  });

  it("does not keep a filtered-out scenario open, and remembers which one it was", () => {
    const visible = filterScenarios(all, {
      ...NO_EXPLORER_FILTERS,
      severity: "low",
    });
    expect(resolveDetail(all, visible, "A-1")).toEqual({
      kind: "hidden",
      id: "A-1",
    });
  });

  it("restores the same scenario once the filters are cleared", () => {
    const visible = filterScenarios(all, NO_EXPLORER_FILTERS);
    expect(resolveDetail(all, visible, "A-1")).toEqual({
      kind: "open",
      scenario: a,
    });
  });

  it("shows nothing for no selection or an id the registry does not have", () => {
    expect(resolveDetail(all, all, null)).toEqual({ kind: "none" });
    expect(resolveDetail(all, all, "Z-9")).toEqual({ kind: "none" });
  });
});
