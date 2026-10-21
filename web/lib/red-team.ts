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

/** DERIVED from evaluatorStatus: what a judge-assisted execution did, by whether its
 * result was obtained. Only a completed execution depended on the judge. When the
 * evaluator was unavailable the judge may not have run, so the record's call count is
 * stated as recorded and nothing is inferred from it. A safety-bound skip is handled
 * before this is called. */
export function judgeAssistedModeMeaning(e: ExecutionRecord): string {
  const calls = `${e.gemini_calls} Gemini ${e.gemini_calls === 1 ? "call" : "calls"}`;
  const recorded = `The record shows ${calls} at a recorded cost of ${formatCost(e.cost_usd)}.`;
  switch (evaluatorStatus(e)) {
    case "pending":
      return "This is a judge-assisted execution that has not finished, so no result has been recorded and nothing has been exercised yet.";
    case "unavailable":
      return `This was a judge-assisted execution, but the evaluator could not run, so the defense was not assessed and the judge may not have run. ${recorded}`;
    case "not_reached":
      return "This was a judge-assisted execution, but the harness stopped before it reached the defense. No result was obtained.";
    case "available":
      return `This was a judge-assisted execution. Detection depended on the Gemini faithfulness judge. It made ${calls} at a recorded cost of ${formatCost(e.cost_usd)}.`;
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

// ---------------------------------------------------------------------------
// The defense lanes: where in a request's path each scenario's target layer sits.
// ---------------------------------------------------------------------------

export type Stage = "input" | "retrieval" | "output";

export const STAGE_LABEL: Record<Stage, string> = {
  input: "Input rails",
  retrieval: "Retrieval",
  output: "Output rails",
};

/** The target layers in the order a request meets them. A layer the registry adds that is
 * not listed here is shown after these, under its own name, with no stage. */
export const LAYER_ORDER: readonly string[] = [
  "prompt-guard-2",
  "llama-guard-3",
  "pii-redaction",
  "retrieval-rail",
  "schema-enforcement",
  "regulated-phrases",
  "faithfulness",
];

const LAYER_STAGE: Record<string, Stage> = {
  "prompt-guard-2": "input",
  "llama-guard-3": "input",
  "pii-redaction": "input",
  "retrieval-rail": "retrieval",
  "schema-enforcement": "output",
  "regulated-phrases": "output",
  faithfulness: "output",
};

export function stageOf(layer: string): Stage | null {
  return LAYER_STAGE[layer] ?? null;
}

export interface Lane {
  layer: string;
  stage: Stage | null;
  scenarios: ScenarioView[];
}

/** DERIVED from the registry's target_layer. Lanes follow the path of a request, scenarios
 * inside a lane follow their id, and a lane with no scenario is omitted. */
export function groupByLayer(scenarios: ScenarioView[]): Lane[] {
  const layers = [
    ...LAYER_ORDER,
    ...[...new Set(scenarios.map((s) => s.target_layer))]
      .filter((l) => !LAYER_ORDER.includes(l))
      .sort(),
  ];
  return layers
    .map((layer) => ({
      layer,
      stage: stageOf(layer),
      scenarios: scenarios
        .filter((s) => s.target_layer === layer)
        .sort((a, b) => a.id.localeCompare(b.id)),
    }))
    .filter((lane) => lane.scenarios.length > 0);
}

// ---------------------------------------------------------------------------
// Explorer filters. Every field is one the registry or the latest stored result carries.
// ---------------------------------------------------------------------------

export interface ExplorerFilters {
  result: Outcome | "not_run" | "";
  severity: Severity | "";
  mode: Mode | "";
  category: Category | "";
}

export const NO_EXPLORER_FILTERS: ExplorerFilters = {
  result: "",
  severity: "",
  mode: "",
  category: "",
};

export function hasExplorerFilters(f: ExplorerFilters): boolean {
  return Boolean(f.result || f.severity || f.mode || f.category);
}

export function filterScenarios(
  scenarios: ScenarioView[],
  f: ExplorerFilters,
): ScenarioView[] {
  return scenarios.filter((s) => {
    if (f.severity && s.severity !== f.severity) return false;
    if (f.mode && s.mode !== f.mode) return false;
    if (f.category && s.category !== f.category) return false;
    if (f.result) {
      const last = s.last_execution?.outcome ?? null;
      if (f.result === "not_run" ? last !== null : last !== f.result) {
        return false;
      }
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// History. Executions of one scenario, oldest first, collapsed into runs of the same result.
// ---------------------------------------------------------------------------

function startedAt(e: ExecutionRecord): number {
  return Date.parse(e.started_at ?? e.finished_at ?? "") || 0;
}

/** Oldest first. Executions without a start time (queued) sort last, in seq order. */
export function oldestFirst(executions: ExecutionRecord[]): ExecutionRecord[] {
  return [...executions].sort(
    (a, b) =>
      (a.started_at === null ? Infinity : startedAt(a)) -
        (b.started_at === null ? Infinity : startedAt(b)) || a.seq - b.seq,
  );
}

export function byScenario(
  executions: ExecutionRecord[],
): Map<string, ExecutionRecord[]> {
  const map = new Map<string, ExecutionRecord[]>();
  for (const e of oldestFirst(executions)) {
    map.set(e.scenario_id, [...(map.get(e.scenario_id) ?? []), e]);
  }
  return map;
}

/** One result as the history tells it. Two executions are the same result when the scenario
 * version, the outcome, the expectation and the safety-bound marker all agree. */
export function resultKey(e: ExecutionRecord): string {
  return [
    e.scenario_version,
    e.outcome ?? e.state,
    e.expectation ?? "",
    isSafetyBoundSkip(e) ? "skip" : "",
  ].join("|");
}

export interface Streak {
  key: string;
  executions: ExecutionRecord[];
  first: ExecutionRecord;
  last: ExecutionRecord;
}

/** DERIVED. Consecutive executions with the same result collapse into one streak, so
 * fourteen identical re-runs read as one line with a count and the dates they span. The
 * individual executions stay on the streak and are never dropped. */
export function streaks(oldest: ExecutionRecord[]): Streak[] {
  const out: Streak[] = [];
  for (const e of oldest) {
    const tail = out[out.length - 1];
    if (tail && tail.key === resultKey(e)) {
      tail.executions.push(e);
      tail.last = e;
    } else {
      out.push({ key: resultKey(e), executions: [e], first: e, last: e });
    }
  }
  return out;
}

export type Change =
  | "regression"
  | "lost_result"
  | "recovery"
  | "expectation_lost"
  | "expectation_regained"
  | "new_version";

export const CHANGE_LABEL: Record<Change, string> = {
  regression: "Caught before, missed now",
  lost_result: "Caught before, no result now",
  recovery: "Missed before, caught now",
  expectation_lost: "Matched before, differs now",
  expectation_regained: "Differed before, matches now",
  new_version: "New scenario version",
};

/** DERIVED. What changed between two consecutive finished executions of one scenario, or null
 * when nothing a reader should be told about did. A regression is the signal the incident
 * agent's red_team_miss trigger looks for: a defense that held and stopped holding. An outcome
 * change outranks a version change, and a version change with the same result is reported
 * because the later result is not a repeat of the earlier one. */
export function changeBetween(
  prev: ExecutionRecord,
  next: ExecutionRecord,
): Change | null {
  if (prev.outcome === null || next.outcome === null) return null;
  if (prev.outcome === "caught" && next.outcome === "missed") {
    return "regression";
  }
  if (prev.outcome === "caught" && next.outcome !== "caught") {
    return "lost_result";
  }
  if (prev.outcome === "missed" && next.outcome === "caught") {
    return "recovery";
  }
  if (prev.expectation === "met" && next.expectation === "not_met") {
    return "expectation_lost";
  }
  if (prev.expectation === "not_met" && next.expectation === "met") {
    return "expectation_regained";
  }
  if (prev.scenario_version !== next.scenario_version) return "new_version";
  return null;
}

/** DERIVED. The change that led into each streak, keyed by the streak's index. The first
 * streak has none. */
export function streakChanges(list: Streak[]): (Change | null)[] {
  return list.map((s, i) =>
    i === 0 ? null : changeBetween(list[i - 1].last, s.first),
  );
}

// ---------------------------------------------------------------------------
// What needs attention.
// ---------------------------------------------------------------------------

export type AttentionKind =
  | "regression"
  | "missed"
  | "known_gap"
  | "differs"
  | "lost_result"
  | "unavailable"
  | "failed"
  | "skipped"
  | "inconclusive";

export interface AttentionItem {
  scenario: ScenarioView;
  kind: AttentionKind;
  execution: ExecutionRecord;
  /** The streak change that led to this result, when the history shows one. */
  change: Change | null;
}

const ATTENTION_RANK: Record<AttentionKind, number> = {
  regression: 0,
  missed: 1,
  differs: 2,
  lost_result: 3,
  known_gap: 4,
  unavailable: 5,
  failed: 6,
  inconclusive: 7,
  skipped: 8,
};

export const ATTENTION_LABEL: Record<AttentionKind, string> = {
  regression: "Caught before, missed now",
  missed: "Missed, and expected to be caught",
  known_gap: "Known gap, still missed",
  differs: "Caught, but not as expected",
  lost_result: "Caught before, no result now",
  unavailable: "Evaluator could not run",
  failed: "Execution failed",
  skipped: "Not run (safety bound)",
  inconclusive: "Inconclusive",
};

/** DERIVED from the latest finished execution of each scenario and its history. A scenario
 * that was caught as expected needs no attention and is omitted. A scenario never run is not
 * an attention item, because no result exists to read. Ranked: a defense that stopped holding,
 * then an unexpected miss, then a result that differs, then everything that says nothing about
 * a defense. Within a rank, higher severity first, then id. */
export function attentionItems(
  scenarios: ScenarioView[],
  history: Map<string, ExecutionRecord[]>,
): AttentionItem[] {
  const items: AttentionItem[] = [];
  for (const scenario of scenarios) {
    const last = scenario.last_execution;
    if (last === null || last.outcome === null) continue;
    const list = streaks(history.get(scenario.id) ?? []);
    const changes = streakChanges(list);
    const index = list.findIndex((s) =>
      s.executions.some((e) => e.execution_id === last.execution_id),
    );
    const change = index >= 0 ? changes[index] : null;
    let kind: AttentionKind | null = null;
    if (last.outcome === "missed") {
      if (change === "regression") kind = "regression";
      else if (last.expected.known_gap && last.expectation === "met") {
        kind = "known_gap";
      } else kind = "missed";
    } else if (last.outcome === "caught") {
      if (last.expectation === "not_met") kind = "differs";
    } else if (last.outcome === "evaluator_unavailable") kind = "unavailable";
    else if (last.outcome === "execution_failed") {
      kind = isSafetyBoundSkip(last) ? "skipped" : "failed";
    } else kind = "inconclusive";
    if (kind === null) continue;
    items.push({
      scenario,
      kind: change === "lost_result" ? "lost_result" : kind,
      execution: last,
      change,
    });
  }
  return items.sort(
    (a, b) =>
      ATTENTION_RANK[a.kind] - ATTENTION_RANK[b.kind] ||
      SEVERITY_ORDER[a.scenario.severity] -
        SEVERITY_ORDER[b.scenario.severity] ||
      a.scenario.id.localeCompare(b.scenario.id),
  );
}

/** Whether an attention item is one a person can open an incident investigation on. The
 * trigger is red_team_miss, so it is offered for a miss and for a caught result that differs
 * from what was expected, and for nothing that says nothing about a defense. */
export function canInvestigate(e: ExecutionRecord): boolean {
  return (
    e.state === "finished" &&
    (e.outcome === "missed" || e.expectation === "not_met")
  );
}

/** DERIVED. Executions counted by outcome, over everything loaded. */
export function countExecutions(
  executions: ExecutionRecord[],
): Record<Outcome, number> {
  const counts: Record<Outcome, number> = {
    caught: 0,
    missed: 0,
    evaluator_unavailable: 0,
    execution_failed: 0,
    inconclusive: 0,
  };
  for (const e of executions) if (e.outcome !== null) counts[e.outcome] += 1;
  return counts;
}

/** The sentence a reader gets first. It says what the stored results show and never infers
 * that nothing is wrong from results that do not exist. */
export function findingHeadline(
  summary: LatestSummary,
  items: AttentionItem[],
): string {
  if (summary.scenarioCount === 0) return "The scenario registry is empty.";
  const run = summary.scenarioCount - summary.notRun;
  if (run === 0) {
    return "No scenario has been run, so there are no results to read yet.";
  }
  const count = (n: number, one: string, many: string) =>
    `${n} ${n === 1 ? one : many}`;
  const of = (kind: AttentionKind) =>
    items.filter((i) => i.kind === kind).length;
  const regressions = of("regression") + of("lost_result");
  const unexpected = of("missed");
  const differs = of("differs");
  const gaps = of("known_gap");
  const silent =
    of("unavailable") + of("failed") + of("skipped") + of("inconclusive");
  const parts: string[] = [];
  if (regressions > 0) {
    parts.push(
      `${count(regressions, "scenario was", "scenarios were")} caught before and ${regressions === 1 ? "is" : "are"} not now.`,
    );
  }
  if (unexpected > 0) {
    parts.push(
      `${count(unexpected, "scenario was", "scenarios were")} missed and expected to be caught.`,
    );
  }
  if (differs > 0) {
    parts.push(
      `${count(differs, "result was", "results were")} caught by a different layer than expected.`,
    );
  }
  if (parts.length === 0 && gaps > 0) {
    parts.push(
      `${count(gaps, "known gap remains", "known gaps remain")} open and still missed, as the scenario expected.`,
    );
  } else if (gaps > 0) {
    parts.push(
      `${count(gaps, "known gap is", "known gaps are")} still missed, as expected.`,
    );
  }
  if (silent > 0) {
    parts.push(
      `${count(silent, "result says", "results say")} nothing about a defense.`,
    );
  }
  const held = items.length === 0 ? run : summary.counts.caught - differs;
  if (parts.length === 0) {
    return `${run === 1 ? "The one scenario" : `All ${run} scenarios`} with a result held as expected.${summary.notRun > 0 ? ` ${summary.notRun} have not been run.` : ""}`;
  }
  parts.push(
    `${count(Math.max(held, 0), "other scenario held", "other scenarios held")} as expected${summary.notRun > 0 ? `, and ${summary.notRun} ${summary.notRun === 1 ? "has" : "have"} not been run` : ""}.`,
  );
  return parts.join(" ");
}

/** The result a streak stands for, in lowercase words. */
export function streakWord(s: Streak): string {
  if (isSafetyBoundSkip(s.last)) return "not run (safety bound)";
  return s.last.outcome
    ? OUTCOME_LABEL[s.last.outcome].toLowerCase()
    : "pending";
}

/** DERIVED. One line for a scenario's history: how many executions and whether the result
 * ever changed. */
export function historySummary(list: Streak[]): string {
  const total = list.reduce((n, s) => n + s.executions.length, 0);
  if (total === 0) return "Not run";
  const word = `${total} ${total === 1 ? "execution" : "executions"}`;
  if (list.length === 1) {
    return total === 1
      ? `1 execution, ${streakWord(list[0])}`
      : `${word}, all ${streakWord(list[0])}`;
  }
  return `${word}, ${list.length} different results`;
}
