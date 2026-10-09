import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EvidenceBody } from "@/components/red-team-evidence";
import type { ExecutionRecord, Outcome } from "@/lib/red-team";

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
    expected: {
      outcome: "caught",
      layer: "prompt-guard-2",
      check: null,
      known_gap: false,
      rationale: "r",
    },
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

function modeSection(e: ExecutionRecord): string {
  const html = renderToStaticMarkup(<EvidenceBody e={e} executor={null} />);
  const start = html.indexOf(">Mode<");
  const end = html.indexOf(">Trace<");
  return html.slice(start, end);
}

const EXERCISED = "exercised the real defense";

describe("deterministic Mode copy follows the outcome", () => {
  it.each<Outcome>(["caught", "missed", "inconclusive"])(
    "keeps the exercised wording for a completed %s execution",
    (outcome) => {
      expect(modeSection(execution({ outcome }))).toContain(EXERCISED);
    },
  );

  it("says the defense was not assessed when the evaluator was unavailable", () => {
    const html = modeSection(
      execution({ outcome: "evaluator_unavailable", acting_layer: null }),
    );
    expect(html).not.toContain(EXERCISED);
    expect(html).toContain("was not assessed");
  });

  it("says no result was obtained when the execution failed", () => {
    const html = modeSection(
      execution({ outcome: "execution_failed", acting_layer: null }),
    );
    expect(html).not.toContain(EXERCISED);
    expect(html).toContain("No result was obtained");
  });

  it("does not claim an exercise for an execution that has not finished", () => {
    const html = modeSection(
      execution({ state: "running", outcome: null, expectation: null }),
    );
    expect(html).not.toContain(EXERCISED);
  });

  it("keeps the safety-bound skip copy", () => {
    const html = modeSection(
      execution({
        outcome: "execution_failed",
        evidence: { skipped_by_safety_bound: true },
      }),
    );
    expect(html).toContain("was not run, so no defense was exercised");
  });
});
