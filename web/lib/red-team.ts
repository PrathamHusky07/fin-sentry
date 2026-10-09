/**
 * Mirrors finsentry/redteam/records.py and finsentry/redteam/api.py field for
 * field, with Pydantic's snake_case names. Everything the console shows comes
 * from these persisted shapes or is derived from them by the pure functions
 * below. Nothing here is a default, a sample or a rate that was not measured.
 *
 * Provenance (see ../CLAUDE.md):
 * - PERSISTED: every field of ExecutionRecord and RunRecord.
 * - DERIVED: summarizeLatest, evaluatorStatus, expectationLabel, runProgress,
 *   continuationState, isSafetyBoundSkip. Each is computed from persisted rows
 *   and documented where it is defined.
 */

export type Outcome =
  | "caught"
  | "missed"
  | "evaluator_unavailable"
  | "execution_failed"
  | "inconclusive";

export type Expectation = "met" | "not_met" | "not_assessable";
export type Mode = "deterministic" | "judge_assisted";
export type Severity = "low" | "medium" | "high" | "critical";
export type ExecutionState = "queued" | "running" | "finished";
export type RunStatus = "running" | "completed" | "failed";

export type Category =
  | "direct_injection"
  | "hazard_content"
  | "pii"
  | "multi_stage"
  | "indirect_injection"
  | "output_schema"
  | "regulated_phrase"
  | "unsupported_claim"
  | "citation_integrity";

export interface Expected {
  outcome: "caught" | "missed";
  layer: string | null;
  check: string | null;
  known_gap: boolean;
  rationale: string;
}

export interface ExecutionRecord {
  execution_id: string;
  run_id: string;
  seq: number;
  scenario_id: string;
  scenario_version: number;
  category: Category;
  target_layer: string;
  mode: Mode;
  expected: Expected;
  state: ExecutionState;
  outcome: Outcome | null;
  acting_layer: string | null;
  acting_check: string | null;
  expectation: Expectation | null;
  reason: string | null;
  evidence: Record<string, unknown>;
  trace_ref: string | null;
  gemini_calls: number;
  cost_usd: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface RunRecord {
  run_id: string;
  created_at: string;
  finished_at: string | null;
  status: RunStatus;
  scenario_ids: string[];
  allow_judge_assisted: boolean;
  failure_reason: string | null;
  total: number;
  finished: number;
  outcome_counts: Partial<Record<Outcome, number>>;
}

export interface ScenarioView {
  id: string;
  version: number;
  title: string;
  category: Category;
  target_layer: string;
  description: string;
  executor: string;
  mode: Mode;
  expected: Expected;
  required_evidence: string[];
  severity: Severity;
  severity_rationale: string;
  input: Record<string, unknown>;
  last_execution: ExecutionRecord | null;
}

export interface ScenarioList {
  scenarios: ScenarioView[];
  persistence_available: boolean;
}

export interface RunDetail {
  run: RunRecord;
  executions: ExecutionRecord[];
}

export interface ExecutionList {
  executions: ExecutionRecord[];
  next_offset: number | null;
}

export const OUTCOMES: readonly Outcome[] = [
  "caught",
  "missed",
  "evaluator_unavailable",
  "execution_failed",
  "inconclusive",
];

export const OUTCOME_LABEL: Record<Outcome, string> = {
  caught: "Caught",
  missed: "Missed",
  evaluator_unavailable: "Evaluator unavailable",
  execution_failed: "Execution failed",
  inconclusive: "Inconclusive",
};

export const OUTCOME_MEANING: Record<Outcome, string> = {
  caught:
    "A defense layer acted on the attack, and the evidence shows what it did.",
  missed:
    "The attack passed every relevant defense. This is a finding, not an error.",
  evaluator_unavailable:
    "A rail or judge could not run. No defense is credited, because none ran.",
  execution_failed:
    "The execution produced no result, so nothing was learned about any defense. Either the test harness failed, or the scenario was intentionally not run to bound cost.",
  inconclusive:
    "The execution finished, but the evidence cannot support caught or missed.",
};

/** The only outcome that means a defense worked. The console never shows any
 * other outcome as a detection, and a test pins this. */
export function isDetection(outcome: Outcome | null): boolean {
  return outcome === "caught";
}

export const CATEGORY_LABEL: Record<Category, string> = {
  direct_injection: "Direct prompt injection",
  indirect_injection: "Indirect injection in retrieved text",
  hazard_content: "Hazardous requests",
  pii: "Personal data",
  multi_stage: "Multi-stage attacks",
  output_schema: "Output schema",
  regulated_phrase: "Regulated phrases",
  unsupported_claim: "Unsupported financial claims",
  citation_integrity: "Citation integrity",
};

/** Input side first, then retrieval, then output: the order a request travels. */
export const CATEGORY_ORDER: readonly Category[] = [
  "direct_injection",
  "hazard_content",
  "pii",
  "multi_stage",
  "indirect_injection",
  "output_schema",
  "regulated_phrase",
  "unsupported_claim",
  "citation_integrity",
];

export const LAYER_LABEL: Record<string, string> = {
  "prompt-guard-2": "Prompt Guard 2",
  "pii-redaction": "PII redaction",
  "llama-guard-3": "Llama Guard 3",
  "retrieval-rail": "Retrieval rail",
  "schema-enforcement": "Schema enforcement",
  "regulated-phrases": "Regulated phrases",
  faithfulness: "Faithfulness",
};

export function layerLabel(layer: string | null): string {
  if (layer === null) return "None";
  return LAYER_LABEL[layer] ?? layer;
}

export const MODE_LABEL: Record<Mode, string> = {
  deterministic: "Deterministic",
  judge_assisted: "Judge-assisted",
};

export const MODE_MEANING: Record<Mode, string> = {
  deterministic:
    "A real defense with a controlled input. The runner makes no billable model calls. A gateway request that no input rail stops continues to the model path, where a bounded Gemini cost is possible.",
  judge_assisted:
    "Detection depends on the Gemini faithfulness judge, so this run spends model calls.",
};

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

/** What the scenario expected, in words: "Caught by Prompt Guard 2" or
 * "Missed (known gap)". Stored with the scenario, never with the result. */
export function expectedLabel(expected: Expected): string {
  if (expected.outcome === "missed") {
    return expected.known_gap ? "Missed (known gap)" : "Missed";
  }
  const check = expected.check ? `, ${expected.check} check` : "";
  return `Caught by ${layerLabel(expected.layer)}${check}`;
}

/** DERIVED: how the observed outcome relates to the stored expectation. A
 * confirmed known gap reads as such, so an expected miss is not shown as a
 * defense failure and not shown as a success either. */
export function expectationLabel(e: ExecutionRecord): string {
  if (e.state !== "finished") return "Pending";
  if (e.expectation === "met") {
    return e.expected.known_gap ? "Known gap confirmed" : "Matches expectation";
  }
  if (e.expectation === "not_met") return "Differs from expectation";
  return "Not assessable";
}

export type EvaluatorStatus =
  "pending" | "available" | "unavailable" | "not_reached";

/** DERIVED from the outcome: an evaluator_unavailable execution means a rail or
 * judge could not run, execution_failed means the harness stopped before one
 * could, and every other finished outcome means the evaluator ran. */
export function evaluatorStatus(e: ExecutionRecord): EvaluatorStatus {
  if (e.state !== "finished") return "pending";
  if (e.outcome === "evaluator_unavailable") return "unavailable";
  if (e.outcome === "execution_failed") return "not_reached";
  return "available";
}

export const EVALUATOR_LABEL: Record<EvaluatorStatus, string> = {
  pending: "Pending",
  available: "Ran",
  unavailable: "Could not run",
  not_reached: "Not reached",
};

/** True when the execution made a request to the gateway route, which is the
 * only kind that leaves a persisted trace to open in Investigations. */
export function sentGatewayRequest(e: ExecutionRecord): boolean {
  return "gateway_status" in e.evidence;
}

/** DERIVED: a gateway_route execution that carries neither continuation evidence
 * nor a gateway response, as legacy rows do. The record cannot say whether a
 * request was sent, so the console must not claim either. `executor` comes from
 * the scenario registry, since executions do not store it. An unresolved
 * executor (null) is treated the same way, because "no gateway request" cannot
 * be asserted for it either. */
export function gatewayProvenanceUnrecorded(
  e: ExecutionRecord,
  executor: string | null,
): boolean {
  return (
    (executor === null || executor === "gateway_route") &&
    !isSafetyBoundSkip(e) &&
    continuationState(e) === "not_recorded" &&
    !sentGatewayRequest(e)
  );
}

/** The runner writes this evidence key when a gateway execution failed or timed
 * out. It means a request was attempted but nothing recorded how far it got. */
const CONTINUATION_UNKNOWN_KEY = "continuation_unknown";
/** The runner writes this evidence key on a scenario it deliberately did not
 * run because an earlier gateway request in the run had already continued past
 * the input rails. Read from a structured key, never from the reason prose. */
const SAFETY_BOUND_KEY = "skipped_by_safety_bound";

export type Continuation = "continued" | "stopped" | "unknown" | "not_recorded";

/** DERIVED from the evidence the runner stored: did a gateway request go past
 * the input rails? "unknown" is its own state and is never read as "stopped".
 * "not_recorded" is every execution that makes no claim either way. */
export function continuationState(e: ExecutionRecord): Continuation {
  if (e.evidence[CONTINUATION_UNKNOWN_KEY] === true) return "unknown";
  if (e.evidence.continued_past_input_rails === true) return "continued";
  if (e.evidence.continued_past_input_rails === false) return "stopped";
  return "not_recorded";
}

export const CONTINUATION_LABEL: Record<
  Exclude<Continuation, "not_recorded">,
  string
> = {
  continued: "Continued past the input rails (Gemini calls possible)",
  stopped: "Did not continue",
  unknown: "Interrupted, continuation unknown",
};

export const CONTINUATION_MEANING: Record<
  Exclude<Continuation, "not_recorded">,
  string
> = {
  continued:
    "No input rail stopped this request, so it continued to the faithfulness rail and the flash judge. Either can call Gemini, and those calls are not recorded on this execution. The rails' cost limits cap them.",
  stopped:
    "An input rail stopped this request, or could not run, so it ended before retrieval, the model and the faithfulness judge.",
  unknown:
    "The execution was interrupted before it recorded whether a request was sent or went past the input rails. That is unknown. If a request did go further, it may have reached the model path, where Gemini calls are possible. The run counted it against its one-continuation limit.",
};

/** DERIVED: a scenario the runner intentionally did not run to bound cost. Its
 * persisted outcome is still execution_failed, which the five-state taxonomy
 * requires, so this is the only place the two cases are told apart. */
export function isSafetyBoundSkip(e: ExecutionRecord): boolean {
  return (
    e.outcome === "execution_failed" && e.evidence[SAFETY_BOUND_KEY] === true
  );
}

/** DERIVED from evaluatorStatus: what a deterministic execution did, by what it
 * reached. Only a completed execution exercised the defense. A safety-bound skip
 * is handled before this is called. */
export function deterministicModeMeaning(e: ExecutionRecord): string {
  const tail =
    "The runner made no model call of its own. It is not a measurement of live model behavior.";
  switch (evaluatorStatus(e)) {
    case "pending":
      return `This is a deterministic execution that has not finished, so nothing has been exercised yet. ${tail}`;
    case "unavailable":
      return `This was a deterministic execution, but the defense could not run, so it was not assessed. ${tail}`;
    case "not_reached":
      return `This was a deterministic execution, but the harness stopped before it reached the defense. No result was obtained. ${tail}`;
    case "available":
      return `This was a deterministic execution. It exercised the real defense with a controlled input. ${tail}`;
  }
}

export const SAFETY_BOUND_LABEL = "Not run (safety bound)";
export const SAFETY_BOUND_MEANING =
  "This scenario was intentionally skipped to bound cost, because an earlier gateway scenario in the run had already continued past the input rails. The harness did not fail, and no defense was exercised.";

export interface LatestSummary {
  scenarioCount: number;
  notRun: number;
  counts: Record<Outcome, number>;
  /** Results whose expectation was not met. */
  differs: number;
  /** Known gaps whose miss was confirmed. */
  gapsConfirmed: number;
  /** Of the execution_failed results, those that were intentionally not run. */
  safetyBoundSkips: number;
}

/** DERIVED from the latest finished execution of each scenario, as returned
 * by GET /ops/redteam/scenarios. Counts scenarios, not executions: a scenario
 * run five times still counts once, by its most recent result. */
export function summarizeLatest(scenarios: ScenarioView[]): LatestSummary {
  const counts: Record<Outcome, number> = {
    caught: 0,
    missed: 0,
    evaluator_unavailable: 0,
    execution_failed: 0,
    inconclusive: 0,
  };
  let notRun = 0;
  let differs = 0;
  let gapsConfirmed = 0;
  let safetyBoundSkips = 0;
  for (const s of scenarios) {
    const last = s.last_execution;
    if (last === null || last.outcome === null) {
      notRun += 1;
      continue;
    }
    counts[last.outcome] += 1;
    if (isSafetyBoundSkip(last)) safetyBoundSkips += 1;
    if (last.expectation === "not_met") differs += 1;
    if (last.expectation === "met" && last.expected.known_gap) {
      gapsConfirmed += 1;
    }
  }
  return {
    scenarioCount: scenarios.length,
    notRun,
    counts,
    differs,
    gapsConfirmed,
    safetyBoundSkips,
  };
}

export function runProgress(run: RunRecord): {
  finished: number;
  total: number;
  percent: number;
} {
  const percent =
    run.total === 0 ? 0 : Math.round((run.finished / run.total) * 100);
  return { finished: run.finished, total: run.total, percent };
}

export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "Not recorded";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function traceHref(traceRef: string): string {
  return `/investigations?trace=${encodeURIComponent(traceRef)}`;
}

/** Groups scenarios by category in request order. Categories with no scenario
 * are omitted, so the list never shows an empty heading. */
export function groupByCategory(
  scenarios: ScenarioView[],
): { category: Category; scenarios: ScenarioView[] }[] {
  return CATEGORY_ORDER.map((category) => ({
    category,
    scenarios: scenarios
      .filter((s) => s.category === category)
      .sort((a, b) => a.id.localeCompare(b.id)),
  })).filter((g) => g.scenarios.length > 0);
}
