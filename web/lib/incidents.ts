/**
 * Mirrors finsentry/investigator/api.py, contracts.py, store.py and timeline.py field for
 * field, with Pydantic's snake_case names. Everything the incident pages show is one of
 * these stored fields or is derived from them by the pure functions below.
 *
 * Provenance (see ../CLAUDE.md):
 * - PERSISTED: every field of InvestigationDetail, including the timeline events, the final
 *   state, the report and the usage.
 * - DERIVED: queryOutcome, hypothesisRows, evidenceRows, timelineSteps, budgetRows,
 *   spendNote, recordHref. Each is computed from persisted fields and documented where it is
 *   defined.
 * - NOT_AVAILABLE: a model's reasoning text (never stored), live progress between events,
 *   and any figure for a session that stored no final state. Those render as "not stored".
 */

export type Status = "running" | "completed" | "failed" | "interrupted";
export type Origin = "live" | "fixture";
export type Outcome = "diagnosis" | "abstention";
export type ToolStatus = "ok" | "empty" | "unavailable" | "rejected";
export type Subsystem =
  | "input_rails"
  | "retrieval"
  | "downstream_model"
  | "output_rails"
  | "judges"
  | "event_pipeline";
export type Confidence = "low" | "medium" | "high";
export type HypothesisStatus = "open" | "supported" | "weakened" | "refuted";
export type StoppingReason =
  | "sufficient_evidence"
  | "justified_abstention"
  | "budget_exhausted"
  | "critical_evidence_unavailable";
export type TriggerKind =
  | "faithfulness_block_cluster"
  | "judge_disagreement_cluster"
  | "red_team_miss"
  | "error_kind_surge"
  | "drift_degradation"
  | "single_trace";

export interface EvidenceRef {
  kind: string;
  record_id: string;
}

export interface Trigger {
  kind: TriggerKind;
  reference_id: string | null;
  description: string;
}

export interface Scope {
  endpoint: string | null;
  ticker: string | null;
  trace_ids: string[];
}

export interface Window {
  start: string;
  end: string;
}

export interface Leading {
  hypothesis_id: string;
  subsystem: Subsystem;
  confidence: Confidence;
  statement: string;
}

export interface Summary {
  investigation_id: string;
  incident_id: string;
  status: Status;
  outcome: Outcome | null;
  origin: Origin;
  planner: string;
  created_at: string;
  finished_at: string | null;
  trigger: Trigger;
  scope: Scope;
  window: Window;
  stopping_reason: StoppingReason | null;
  leading: Leading | null;
  hypotheses: number | null;
  queries: number | null;
  model_calls: number | null;
  cost_usd: number | null;
  error: string | null;
  stale: boolean;
}

export type Fact = string | number | boolean | null;

export interface QueryRun {
  kind: "query";
  query_id: string;
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  error: string | null;
  separates: string[];
  retry_justification: string | null;
  empty_unverified: boolean;
  elapsed_s: number;
  records: Record<string, Record<string, Fact>>;
}

export interface PlannedPrediction {
  tool: string;
  signal: string | null;
  expect: boolean;
  subject: string | null;
  description: string;
  query_key: string | null;
}

export interface PlannedHypothesis {
  hypothesis_id: string;
  subsystem: Subsystem;
  symptom: string;
  statement: string;
  predictions: PlannedPrediction[];
}

export interface ProposedVerification {
  kind: "red_team_scenario" | "read_only_query" | "none_available";
  scenario_id: string | null;
  tool: string | null;
  args: Record<string, unknown> | null;
  rationale: string;
  executed: false;
}

export interface PlanMade {
  kind: "plan";
  round: number;
  planner: string;
  hypotheses: PlannedHypothesis[];
  queries_kept: number;
  notes: string[];
  proposed_verification: ProposedVerification | null;
}

export interface PlanFailed {
  kind: "plan_failed";
  round: number;
  attempt: number;
  error: string;
}

export type PredictionState = "met" | "unmet" | "unknown";

export interface PredictionResult {
  tool: string;
  signal: string;
  expect: boolean;
  subject: string | null;
  description: string;
  state: PredictionState;
  detail: string;
  query_ids: string[];
  restates_trigger: boolean;
}

export interface HypothesisAssessment {
  hypothesis_id: string;
  subsystem: Subsystem;
  symptom: string;
  statement: string;
  status: HypothesisStatus;
  supporting: EvidenceRef[];
  contradicting: EvidenceRef[];
  predictions: PredictionResult[];
  set_aside: string[];
}

export interface Assessed {
  kind: "assessment";
  round: number;
  decision: "diagnose" | "abstain" | "continue";
  hypotheses: HypothesisAssessment[];
  leaders: string[];
  confidence: Record<string, Confidence>;
  notes: string[];
  unresolved: string[];
}

export interface Stopped {
  kind: "stopped";
  stopping_reason: StoppingReason;
  outcome: Outcome;
  why: string;
}

export type TimelineEvent =
  QueryRun | PlanMade | PlanFailed | Assessed | Stopped;

export interface TimelineEntry {
  seq: number;
  at: string;
  elapsed_s: number;
  event: TimelineEvent;
}

export interface Claim {
  statement: string;
  evidence: EvidenceRef[];
}

export interface RankedHypothesis {
  hypothesis_id: string;
  rank: number;
  subsystem: Subsystem;
  statement: string;
  confidence: Confidence;
  supporting: EvidenceRef[];
  contradicting: EvidenceRef[];
}

export interface Report {
  incident_id: string;
  outcome: Outcome;
  ranked_hypotheses: RankedHypothesis[];
  observations: Claim[];
  correlations: Claim[];
  causal_claims: Claim[];
  missing_evidence: string[];
  evidence_against: {
    hypothesis_id: string;
    statement: string;
    evidence: EvidenceRef[];
  }[];
  tool_unavailable: string[];
  empty_results: string[];
  tests_actually_run: string[];
  proposed_verification: ProposedVerification;
  limitations: string[];
  stopping_reason: StoppingReason;
  abstention_statement: string | null;
}

export interface ExecutedQuery {
  query_id: string;
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  evidence: EvidenceRef[];
  error: string | null;
  retry_justification: string | null;
  empty_unverified: boolean;
  separates: string[];
}

export interface Budgets {
  max_tool_calls: number;
  max_inference_calls: number;
  max_hypothesis_rounds: number;
  max_wall_clock_s: number;
}

export interface BudgetUsage {
  tool_calls: number;
  inference_calls: number;
  hypothesis_rounds: number;
  wall_clock_s: number;
}

export interface DataGap {
  source: string;
  kind: string;
  detail: string;
}

export interface State {
  incident_id: string;
  hypotheses: {
    hypothesis_id: string;
    statement: string;
    subsystem: Subsystem;
    status: HypothesisStatus;
    symptom: string;
    supporting: EvidenceRef[];
    contradicting: EvidenceRef[];
  }[];
  executed_queries: ExecutedQuery[];
  known_data_gaps: DataGap[];
  unresolved_questions: string[];
  budgets: Budgets;
  usage: BudgetUsage;
  status: "running" | "stopped";
  stopping_reason: StoppingReason | null;
}

export interface ModelUsage {
  planner: string;
  calls: number;
  unmetered_calls: number;
  prompt_tokens: number;
  candidates_tokens: number;
  thought_tokens: number;
  cost_usd: number;
  call_log: {
    round: number;
    outcome: string;
    error_class: string | null;
    elapsed_s: number;
    cost_usd: number;
  }[];
}

export interface Usage {
  budgets: Budgets;
  used: BudgetUsage;
  model: ModelUsage;
}

export interface Detail extends Summary {
  heartbeat_at: string;
  timeline: TimelineEntry[];
  state: State | null;
  report: Report | null;
  usage: Usage | null;
}

export interface Listing {
  investigations: Summary[];
  next_offset: number | null;
}

export interface Started {
  investigation: Summary;
  created: boolean;
}

// Labels. Plain words for the stored codes, each stated once.

export const TRIGGER_LABEL: Record<TriggerKind, string> = {
  faithfulness_block_cluster: "Faithfulness block cluster",
  judge_disagreement_cluster: "Judge disagreement cluster",
  red_team_miss: "Red Team miss",
  error_kind_surge: "Error kind surge",
  drift_degradation: "Judge drift",
  single_trace: "Single trace",
};

export const SUBSYSTEM_LABEL: Record<Subsystem, string> = {
  input_rails: "Input rails",
  retrieval: "Retrieval",
  downstream_model: "Downstream model",
  output_rails: "Output rails",
  judges: "Judges",
  event_pipeline: "Event pipeline",
};

export const STATUS_LABEL: Record<Status, string> = {
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  interrupted: "Interrupted",
};

export const STATUS_MEANING: Record<Status, string> = {
  running:
    "The investigation is still working. This page shows what it has stored so far.",
  completed:
    "The investigation finished and stored a report. An abstention is a completed outcome.",
  failed:
    "The investigator raised an error. The last good state it reached is kept.",
  interrupted:
    "The process running it stopped before it finished. It was not resumed, so a new investigation is needed to look again.",
};

export const STOPPING_LABEL: Record<StoppingReason, string> = {
  sufficient_evidence: "Sufficient evidence",
  justified_abstention: "Justified abstention",
  budget_exhausted: "Budget exhausted",
  critical_evidence_unavailable: "Critical evidence unavailable",
};

export const STOPPING_MEANING: Record<StoppingReason, string> = {
  sufficient_evidence:
    "A leading hypothesis met every prediction it made and no rival was also supported.",
  justified_abstention:
    "The retrieved records did not support a root cause, so the investigator said so instead of guessing.",
  budget_exhausted:
    "A ceiling on tool calls, model calls, rounds or time was reached before the evidence settled.",
  critical_evidence_unavailable:
    "The tool the investigation cannot do without could not be read, so no later step could supply it.",
};

export const HYPOTHESIS_STATUS_LABEL: Record<HypothesisStatus, string> = {
  supported: "Supported",
  open: "Open",
  weakened: "Weakened",
  refuted: "Refuted",
};

export const HYPOTHESIS_STATUS_MEANING: Record<HypothesisStatus, string> = {
  supported:
    "Records show what it predicted. Supported is not proven: the review checks a hypothesis against its own predictions.",
  open: "No record settled it. Open is not the same as likely.",
  weakened: "Records cut against a prediction it made about an absence.",
  refuted: "Records show its own mechanism is missing.",
};

/** What each closed signal asks, as a sentence fragment that follows "expected". */
export const SIGNAL_LABEL: Record<string, string> = {
  judge_failures: "a cluster of judge pipeline failures",
  judge_drift: "the frontier judge in a drifted state",
  chunk_contradicted: "one chunk cited as contradicting the answer",
  chunk_shared_by_failures: "one chunk shared by the failed traces",
  block_cluster: "a cluster of blocked requests on one rail",
  injection_surge: "a surge of direct injection blocks",
  rail_regression: "a Red Team scenario missed that was expected to be caught",
  rail_working: "a Red Team scenario caught as expected",
  error_cluster: "a cluster of system errors of one kind",
};

export function signalLabel(signal: string): string {
  return SIGNAL_LABEL[signal] ?? signal;
}

const KIND_LABEL: Record<string, string> = {
  trace: "Trace",
  guardrail_decision: "Guardrail decision",
  judge_scores: "Judge scores",
  injection_event: "Injection event",
  drift_report: "Drift report",
  red_team_execution: "Red Team execution",
  query_result: "Query result",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

export function refKey(ref: EvidenceRef): string {
  return `${ref.kind}:${ref.record_id}`;
}

// Query outcomes. Four different things that must never look alike.

export type QueryOutcome =
  | "returned"
  | "verified_empty"
  | "unverified_empty"
  | "unavailable"
  | "rejected";

/** DERIVED from a query's stored status and its empty_unverified flag. A verified empty is
 * the tool saying it matched nothing. An unverified empty came from a transport that cannot
 * tell no rows from a failed query. An unavailable query says nothing about the platform. */
export function queryOutcome(q: {
  status: ToolStatus;
  empty_unverified: boolean;
}): QueryOutcome {
  if (q.status === "ok") return "returned";
  if (q.status === "unavailable") return "unavailable";
  if (q.status === "rejected") return "rejected";
  return q.empty_unverified ? "unverified_empty" : "verified_empty";
}

export const QUERY_OUTCOME_LABEL: Record<QueryOutcome, string> = {
  returned: "Returned records",
  verified_empty: "Ran, matched nothing",
  unverified_empty: "Empty, not verified",
  unavailable: "Could not run",
  rejected: "Rejected",
};

export const QUERY_OUTCOME_MEANING: Record<QueryOutcome, string> = {
  returned: "The tool ran and returned records that can be cited.",
  verified_empty:
    "The tool ran and found nothing. This is a real absence in the window, and it can support a prediction that something is absent.",
  unverified_empty:
    "The tool returned nothing, but this transport cannot tell no rows from a failed query. It is never read as absence.",
  unavailable:
    "The tool could not run, so the result says nothing about the platform. It is not an empty result.",
  rejected:
    "The tool refused the arguments, which is a caller error and is not retried.",
};

// Where a record can be opened.

/** DERIVED. A live record links to the page that shows it. A fixture record exists only
 * inside a replayed case world, so it links nowhere. A drift report has no page of its own. */
export function recordHref(ref: EvidenceRef, origin: Origin): string | null {
  if (origin === "fixture") return null;
  switch (ref.kind) {
    case "trace":
    case "guardrail_decision":
    case "judge_scores":
    case "injection_event":
      return `/investigations?trace=${encodeURIComponent(ref.record_id)}`;
    case "red_team_execution":
      return `/red-team?execution=${encodeURIComponent(ref.record_id)}`;
    default:
      return null;
  }
}

// Hypotheses.

export interface HypothesisRow {
  hypothesis_id: string;
  rank: number | null;
  subsystem: Subsystem;
  statement: string;
  status: HypothesisStatus;
  confidence: Confidence | null;
  supporting: EvidenceRef[];
  contradicting: EvidenceRef[];
  predictions: PredictionResult[];
  set_aside: string[];
  why: string;
  leading: boolean;
}

function lastAssessment(detail: Detail): Assessed | null {
  for (let i = detail.timeline.length - 1; i >= 0; i--) {
    const ev = detail.timeline[i].event;
    if (ev.kind === "assessment") return ev;
  }
  return null;
}

function tally(predictions: PredictionResult[]) {
  const count = (s: PredictionState) =>
    predictions.filter((p) => p.state === s).length;
  return {
    met: count("met"),
    unmet: count("unmet"),
    unknown: count("unknown"),
  };
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** DERIVED sentence for why a hypothesis stands where it does, from its stored predictions
 * and records. It restates counts and never adds a reason the investigator did not record. */
export function whyItRanks(
  h: Pick<
    HypothesisAssessment,
    "status" | "predictions" | "supporting" | "contradicting"
  >,
  leading: boolean,
): string {
  const t = tally(h.predictions);
  const total = h.predictions.length;
  if (total === 0) return "No prediction of this hypothesis could be checked.";
  const base = `${t.met} of ${total} ${total === 1 ? "prediction" : "predictions"} met`;
  if (leading && h.status === "supported" && t.unmet === 0 && t.unknown === 0) {
    return `${base}, none unmet, and no rival for the same symptom is also supported.`;
  }
  if (h.status === "refuted") {
    return `${base}. ${plural(h.contradicting.length, "record")} show its own mechanism is missing.`;
  }
  if (h.status === "weakened") {
    return `${base}. ${plural(h.contradicting.length, "record")} cut against a prediction of absence.`;
  }
  if (h.status === "open") {
    const gaps =
      t.unknown > 0
        ? ` ${plural(t.unknown, "prediction")} could not be checked.`
        : t.unmet > 0
          ? ` ${plural(t.unmet, "prediction")} failed with no record behind it.`
          : " None showed a mechanism of its own.";
    return `${base}.${gaps}`;
  }
  return `${base}${t.unmet ? `, ${t.unmet} unmet` : ""}${t.unknown ? `, ${t.unknown} unchecked` : ""}.`;
}

/** DERIVED. The ranked hypotheses of a report joined to the last assessment's prediction
 * results. A session with no report (failed, interrupted, running) shows the last assessment
 * unranked, or nothing when the investigator never got that far. */
export function hypothesisRows(detail: Detail): HypothesisRow[] {
  const assessed = lastAssessment(detail);
  const byId = new Map(assessed?.hypotheses.map((h) => [h.hypothesis_id, h]));
  if (detail.report && detail.report.ranked_hypotheses.length > 0) {
    const leaders = new Set(assessed?.leaders ?? []);
    return [...detail.report.ranked_hypotheses]
      .sort((a, b) => a.rank - b.rank)
      .map((r) => {
        const a = byId.get(r.hypothesis_id);
        const status =
          detail.state?.hypotheses.find(
            (h) => h.hypothesis_id === r.hypothesis_id,
          )?.status ??
          a?.status ??
          "open";
        const isLeader = leaders.has(r.hypothesis_id);
        return {
          hypothesis_id: r.hypothesis_id,
          rank: r.rank,
          subsystem: r.subsystem,
          statement: r.statement,
          status,
          confidence: r.confidence,
          supporting: r.supporting,
          contradicting: r.contradicting,
          predictions: a?.predictions ?? [],
          set_aside: a?.set_aside ?? [],
          why: whyItRanks(
            {
              status,
              predictions: a?.predictions ?? [],
              supporting: r.supporting,
              contradicting: r.contradicting,
            },
            isLeader,
          ),
          leading: isLeader,
        };
      });
  }
  if (!assessed) return [];
  return assessed.hypotheses.map((h) => ({
    hypothesis_id: h.hypothesis_id,
    rank: null,
    subsystem: h.subsystem,
    statement: h.statement,
    status: h.status,
    confidence: null,
    supporting: h.supporting,
    contradicting: h.contradicting,
    predictions: h.predictions,
    set_aside: h.set_aside,
    why: whyItRanks(h, false),
    leading: false,
  }));
}

// Evidence.

export type EvidenceRole =
  | "supports the leader"
  | "supports another hypothesis"
  | "cuts against a hypothesis"
  | "cited in an observation"
  | "cited in a correlation";

export interface EvidenceRow {
  key: string;
  ref: EvidenceRef;
  roles: EvidenceRole[];
  hypotheses: string[];
  queryIds: string[];
  facts: Record<string, Fact> | null;
}

/** DERIVED. Every record the report cites, with the role each citation plays, the hypotheses
 * it is attached to, the queries that returned it and the facts the tool gave about it when it
 * was read. A citation is only ever one a query returned, which the backend validates. */
export function evidenceRows(detail: Detail): EvidenceRow[] {
  const report = detail.report;
  if (!report) return [];
  const rows = new Map<string, EvidenceRow>();
  const add = (ref: EvidenceRef, role: EvidenceRole, hypothesis?: string) => {
    if (ref.kind === "query_result") return;
    const key = refKey(ref);
    const row = rows.get(key) ?? {
      key,
      ref,
      roles: [],
      hypotheses: [],
      queryIds: [],
      facts: null,
    };
    if (!row.roles.includes(role)) row.roles.push(role);
    if (hypothesis && !row.hypotheses.includes(hypothesis))
      row.hypotheses.push(hypothesis);
    rows.set(key, row);
  };
  for (const h of report.ranked_hypotheses) {
    for (const ref of h.supporting)
      add(
        ref,
        h.rank === 1 ? "supports the leader" : "supports another hypothesis",
        h.hypothesis_id,
      );
    for (const ref of h.contradicting)
      add(ref, "cuts against a hypothesis", h.hypothesis_id);
  }
  for (const a of report.evidence_against)
    for (const ref of a.evidence)
      add(ref, "cuts against a hypothesis", a.hypothesis_id);
  for (const c of report.observations)
    for (const ref of c.evidence) add(ref, "cited in an observation");
  for (const c of report.correlations)
    for (const ref of c.evidence) add(ref, "cited in a correlation");
  for (const entry of detail.timeline) {
    const ev = entry.event;
    if (ev.kind !== "query") continue;
    for (const [key, facts] of Object.entries(ev.records)) {
      const row = rows.get(key);
      if (row) {
        row.facts ??= facts;
        if (!row.queryIds.includes(ev.query_id)) row.queryIds.push(ev.query_id);
      }
    }
  }
  return [...rows.values()];
}

// Timeline.

export interface StatusChange {
  hypothesis_id: string;
  from: HypothesisStatus | null;
  to: HypothesisStatus;
}

export interface Step {
  entry: TimelineEntry;
  changes: StatusChange[];
}

/** DERIVED. The timeline with, for each assessment, how each hypothesis moved since the
 * assessment before it. The first assessment moves hypotheses from nothing. */
export function timelineSteps(detail: Detail): Step[] {
  let previous = new Map<string, HypothesisStatus>();
  return detail.timeline.map((entry) => {
    if (entry.event.kind !== "assessment") return { entry, changes: [] };
    const changes: StatusChange[] = [];
    const next = new Map<string, HypothesisStatus>();
    for (const h of entry.event.hypotheses) {
      next.set(h.hypothesis_id, h.status);
      const from = previous.get(h.hypothesis_id) ?? null;
      if (from !== h.status)
        changes.push({ hypothesis_id: h.hypothesis_id, from, to: h.status });
    }
    previous = next;
    return { entry, changes };
  });
}

// Budget and spend.

export interface BudgetRow {
  label: string;
  used: number;
  max: number;
  unit: string;
}

/** DERIVED from the stored budgets and usage. */
export function budgetRows(usage: Usage, origin: Origin = "live"): BudgetRow[] {
  const { budgets: b, used: u } = usage;
  const rows: BudgetRow[] = [
    {
      label: "Tool calls",
      used: u.tool_calls,
      max: b.max_tool_calls,
      unit: "",
    },
    {
      label: "Model calls",
      used: u.inference_calls,
      max: b.max_inference_calls,
      unit: "",
    },
    {
      label: "Hypothesis rounds",
      used: u.hypothesis_rounds,
      max: b.max_hypothesis_rounds,
      unit: "",
    },
    {
      label: "Wall clock",
      used: Math.round(u.wall_clock_s * 10) / 10,
      max: b.max_wall_clock_s,
      unit: "s",
    },
  ];
  // A fixture replay runs on a stubbed clock, so its wall-clock reading is not a measurement.
  return origin === "fixture"
    ? rows.filter((r) => r.label !== "Wall clock")
    : rows;
}

/** DERIVED. What the model spend figure is and is not. */
export function spendNote(usage: Usage, origin: Origin): string {
  const m = usage.model;
  if (origin === "fixture") {
    return "No model was called. This session replayed a case world with a scripted planner.";
  }
  const base =
    "Counted from the provider's usage metadata at the platform's published rates. It is an estimate, not a bill.";
  return m.unmetered_calls > 0
    ? `${base} ${plural(m.unmetered_calls, "call")} returned no usage and were charged at a pessimistic estimate.`
    : base;
}

export function windowMinutes(w: Window): number {
  return Math.round((Date.parse(w.end) - Date.parse(w.start)) / 60000);
}

export function durationLabel(start: string, end: string | null): string {
  if (!end) return "not finished";
  const ms = Date.parse(end) - Date.parse(start);
  if (ms < 1000) return "under a second";
  const s = Math.round(ms / 1000);
  return s < 90 ? `${s}s` : `${Math.round(s / 60)}m`;
}

export function formatArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([k, v]) => `${k}=${String(v)}`);
  return parts.length === 0 ? "no arguments" : parts.join(", ");
}
