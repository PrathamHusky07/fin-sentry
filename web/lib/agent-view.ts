import {
  QUERY_OUTCOME_LABEL,
  QUERY_OUTCOME_MEANING,
  evidenceRows,
  queryOutcome,
  type Detail,
  type EvidenceRef,
  type HypothesisRow,
  type Origin,
  type PredictionResult,
  type QueryOutcome,
} from "@/lib/incidents";

/**
 * What the Agent pages derive beyond lib/incidents.ts: the mechanism map, the three record
 * states, and the three-layer case file. Provenance (see ../CLAUDE.md):
 * - PERSISTED: nothing here is stored by this file.
 * - DERIVED: queryTally, citationTrace, rivalsOf, missingFor and conclusion, each computed from
 *   persisted session fields and documented where defined.
 * - STATIC: STAGES and the record-state wording describe how the code works and what a label
 *   means. They never say that any one investigation ran, validated or concluded anything.
 */

// The mechanism map.

export type StageId =
  "trigger" | "plan" | "execute" | "assess" | "validate" | "conclude";
export type Actor = "request" | "model" | "code";

export interface Stage {
  id: StageId;
  title: string;
  /** The short word the map draws inside the node. */
  mapLabel: string;
  actor: Actor;
  short: string;
  detail: string;
  /** Where the investigation can end at this stage. Null when no exit starts here. */
  stops: string | null;
  /** Where the stage shows up in a stored case file, or that it does not. */
  inCaseFile: string;
}

export const ACTOR_LABEL: Record<Actor, string> = {
  request: "A request",
  model: "Model proposes",
  code: "Code decides",
};

export const ACTOR_MEANING: Record<Actor, string> = {
  request: "Started by an explicit request, never by opening a page.",
  model: "The only step that calls a model. Nothing it writes can be cited.",
  code: "Deterministic code. No model call.",
};

/** The lifecycle as the implemented loop runs it: open, plan, execute, reassess, diagnose or
 * abstain, with plan validation, the stopping policy and report validation. */
export const STAGES: readonly Stage[] = [
  {
    id: "trigger",
    title: "Trigger",
    mapLabel: "Trigger",
    actor: "request",
    short: "A named incident, its scope and a time window.",
    detail:
      "An investigation starts from one named incident: a faithfulness block cluster, a judge disagreement cluster, a Red Team miss, an error surge, judge drift or a single trace. It always starts from an explicit request. Opening a stored case never starts one.",
    stops:
      "The first read is of the one source the investigation cannot do without. If that source cannot be read twice, or holds nothing for the window, the investigator abstains here.",
    inCaseFile: "The case summary: the trigger, the scope and the time window.",
  },
  {
    id: "plan",
    title: "Plan",
    mapLabel: "Plan",
    actor: "model",
    short: "Competing explanations are proposed.",
    detail:
      "The planner proposes two to four competing hypotheses, each with predictions and the query that would test it. Validation keeps only the queries that tell hypotheses apart and drops the rest. Nothing the planner writes can later be cited as evidence.",
    stops:
      "A plan with fewer than two usable hypotheses ends the investigation as an abstention.",
    inCaseFile:
      "The decision trail: each planning round, with what validation dropped.",
  },
  {
    id: "execute",
    title: "Execute",
    mapLabel: "Execute",
    actor: "code",
    short: "Evidence is retrieved through approved, read-only tools.",
    detail:
      "The surviving queries run through nine read-only tools, each under a call ceiling and a deadline. A query that could not run is recorded as unavailable and is never counted as an empty result. The investigator has no tool that writes anything.",
    stops:
      "A ceiling on tool calls, model calls, rounds or time ends the run with a stated reason.",
    inCaseFile: "The decision trail: each query and the state of its result.",
  },
  {
    id: "assess",
    title: "Assess",
    mapLabel: "Assess",
    actor: "code",
    short: "Each prediction is checked against its own query.",
    detail:
      "A prediction is judged only by the records of the query it names. Another query of the same tool cannot satisfy or contradict it, and a prediction whose query never ran stays unknown. A review then challenges the leading hypothesis with the counter-evidence that was retrieved.",
    stops:
      "The assessment decides the next step: report the leader, abstain, or plan once more while budget remains and the evidence has not settled it.",
    inCaseFile:
      "The hypothesis comparison: every prediction as met, unmet or could not be checked.",
  },
  {
    id: "validate",
    title: "Validate",
    mapLabel: "Validate",
    actor: "code",
    short: "Every citation must trace to an executed query.",
    detail:
      "Every record a claim cites must have been returned by a query that ran. A record that was merely queried is not evidence, and a controlled Red Team result shows how a defense behaves but never what caused an incident.",
    stops:
      "A report that fails validation is replaced by an abstention. It is never stored as a conclusion.",
    inCaseFile:
      "Not stored as an event of its own. A stored report has passed it, and the case file re-traces each cited record to the query that returned it.",
  },
  {
    id: "conclude",
    title: "Conclude or abstain",
    mapLabel: "Conclude",
    actor: "code",
    short: "A best-supported cause, or a stated abstention.",
    detail:
      "A diagnosis is the best-supported hypothesis, checked against its own predictions and the counter-evidence. It is never presented as proven. An abstention is a complete, stored result that says which source was missing or why the records supported no cause.",
    stops: null,
    inCaseFile: "The outcome and the reason the investigation stopped.",
  },
];

export function stageById(id: StageId): Stage {
  return STAGES.find((s) => s.id === id) ?? STAGES[0];
}

/** The loop: after Assess the investigator can plan once more. Everything else is sequential. */
export const LOOP: { from: StageId; to: StageId } = {
  from: "assess",
  to: "plan",
};

export type NodeId = StageId | "incident";
export type LinkKind = "spoke" | "sequence" | "loop";
export interface MapLink {
  id: string;
  from: NodeId;
  to: NodeId;
  kind: LinkKind;
}

/** Every connection the map draws: the incident to each stage, each stage to the next, and
 * the re-plan loop. */
export const LINKS: readonly MapLink[] = [
  ...STAGES.map((s): MapLink => ({
    id: `spoke-${s.id}`,
    from: "incident",
    to: s.id,
    kind: "spoke",
  })),
  ...STAGES.slice(1).map((s, i): MapLink => ({
    id: `seq-${STAGES[i].id}-${s.id}`,
    from: STAGES[i].id,
    to: s.id,
    kind: "sequence",
  })),
  { id: "loop", from: LOOP.from, to: LOOP.to, kind: "loop" },
];

export type NodeState = "rest" | "active" | "related" | "dim";
export type LinkState = "rest" | "lit" | "dim";

/** The stages one connection away from `id` (a neighbour in the sequence, or the other end of
 * the loop). The incident touches every stage, so it never narrows a selection. */
export function relatedStages(id: StageId): StageId[] {
  return LINKS.filter(
    (l) => l.kind !== "spoke" && (l.from === id || l.to === id),
  ).map((l) => (l.from === id ? l.to : l.from) as StageId);
}

export function nodeState(id: NodeId, active: StageId | null): NodeState {
  if (active === null) return "rest";
  if (id === active) return "active";
  if (id === "incident") return "related";
  return relatedStages(active).includes(id) ? "related" : "dim";
}

export function linkState(link: MapLink, active: StageId | null): LinkState {
  if (active === null) return "rest";
  return link.from === active || link.to === active ? "lit" : "dim";
}

/** The next or previous stage in the sequence, wrapping, for arrow-key movement. */
export function stepStage(id: StageId, delta: 1 | -1): StageId {
  const i = STAGES.findIndex((s) => s.id === id);
  return STAGES[(i + delta + STAGES.length) % STAGES.length].id;
}

// Map geometry, in the SVG's own units. Nodes sit on the top half of an ellipse, evenly
// spaced in x, with the incident below the arc and a spoke to every stage.

export const MAP = {
  width: 1000,
  height: 470,
  nodeW: 124,
  nodeH: 60,
  pitch: 150,
  firstX: 125,
  incident: { x: 500, y: 394, r: 64 },
  arc: { cx: 500, cy: 340, rx: 400, ry: 190 },
} as const;

export function stagePosition(index: number): { x: number; y: number } {
  const { cx, cy, rx, ry } = MAP.arc;
  const x = MAP.firstX + index * MAP.pitch;
  const t = (x - cx) / rx;
  return { x, y: cy - ry * Math.sqrt(1 - t * t) };
}

// The three record states.

export type RecordState = "live" | "fixture" | "historical";

export const RECORD_STATE: Record<
  RecordState,
  { label: string; meaning: string }
> = {
  live: {
    label: "Live execution",
    meaning:
      "A record that exists in the platform's stores now. It was read from the running platform through approved, read-only tools, and its model cost is stored with it.",
  },
  fixture: {
    label: "Fixture replay",
    meaning:
      "A controlled, reproducible example: a known case replayed through the same investigator with a scripted planner. No model was called, and it says nothing about the live platform.",
  },
  historical: {
    label: "Historical reference",
    meaning:
      "A preserved capture of a real record, labelled historical. It is not replayed into the pipeline and it is not a current reading.",
  },
};

export function recordStateOf(origin: Origin): "live" | "fixture" {
  return origin === "live" ? "live" : "fixture";
}

// Reading a case file.

export type ReadingId = QueryOutcome | "hypothesis" | "abstained";

export interface ReadingState {
  id: ReadingId;
  /** A query result is one line of the evidence. An outcome is how the whole case ended. */
  kind: "query" | "outcome";
  /** The border rule, stated once: a solid border says something about the platform and a
   * dashed border says nothing about it. True means solid. The case file draws these states
   * with the same rule, and the unit test pins the assignment below. */
  says: boolean;
  label: string;
  meaning: string;
}

/** STATIC. The five query states use the same label and meaning constants the case file
 * renders, so this key cannot drift from it. In reading order: what says something first. */
export const READING_STATES: readonly ReadingState[] = [
  {
    id: "returned",
    kind: "query",
    says: true,
    label: QUERY_OUTCOME_LABEL.returned,
    meaning: QUERY_OUTCOME_MEANING.returned,
  },
  {
    id: "verified_empty",
    kind: "query",
    says: true,
    label: QUERY_OUTCOME_LABEL.verified_empty,
    meaning: QUERY_OUTCOME_MEANING.verified_empty,
  },
  {
    id: "hypothesis",
    kind: "outcome",
    says: true,
    label: "Best-supported hypothesis",
    meaning:
      "The records are consistent with it and no rival is also supported. That is not a proven cause, and the case file says so on the result.",
  },
  {
    id: "unverified_empty",
    kind: "query",
    says: false,
    label: QUERY_OUTCOME_LABEL.unverified_empty,
    meaning: QUERY_OUTCOME_MEANING.unverified_empty,
  },
  {
    id: "unavailable",
    kind: "query",
    says: false,
    label: QUERY_OUTCOME_LABEL.unavailable,
    meaning: QUERY_OUTCOME_MEANING.unavailable,
  },
  {
    id: "rejected",
    kind: "query",
    says: false,
    label: QUERY_OUTCOME_LABEL.rejected,
    meaning: QUERY_OUTCOME_MEANING.rejected,
  },
  {
    id: "abstained",
    kind: "outcome",
    says: false,
    label: "Abstained",
    meaning:
      "The investigation finished and found no supported cause, or could not read the source it needed. It is stored and shown as a complete result, not as an error.",
  },
];

export function readingStateById(id: ReadingId): ReadingState {
  const found = READING_STATES.find((r) => r.id === id);
  if (!found) throw new Error(`unknown reading state ${id}`);
  return found;
}

// The case file.

/** DERIVED. How many of a session's queries ended in each state. */
export function queryTally(detail: Detail): Record<QueryOutcome, number> {
  const tally: Record<QueryOutcome, number> = {
    returned: 0,
    verified_empty: 0,
    unverified_empty: 0,
    unavailable: 0,
    rejected: 0,
  };
  for (const { event } of detail.timeline) {
    if (event.kind === "query") tally[queryOutcome(event)] += 1;
  }
  return tally;
}

export interface CitationTrace {
  cited: number;
  traced: number;
  untraced: EvidenceRef[];
}

/** DERIVED. Every record the report cites, checked against the records the stored queries
 * returned. The backend refuses to store a report whose citations fail this check, so a
 * mismatch here would mean the stored session and the check disagree. Null when no report was
 * stored, because then nothing is cited. */
export function citationTrace(detail: Detail): CitationTrace | null {
  if (!detail.report) return null;
  const rows = evidenceRows(detail);
  const untraced = rows.filter((r) => r.queryIds.length === 0);
  return {
    cited: rows.length,
    traced: rows.length - untraced.length,
    untraced: untraced.map((r) => r.ref),
  };
}

/** DERIVED. The other hypotheses that explain the same symptom as `id`. */
export function rivalsOf(rows: HypothesisRow[], id: string): HypothesisRow[] {
  const self = rows.find((r) => r.hypothesis_id === id);
  if (!self || self.symptom === null) return [];
  return rows.filter(
    (r) => r.hypothesis_id !== id && r.symptom === self.symptom,
  );
}

export interface MissingItem {
  prediction: PredictionResult;
  kind: "unchecked" | "absent";
}

/** DERIVED. The predictions of a hypothesis that no record settled: one whose query never
 * ran or ran without an answer ("unchecked") and one whose expected record was not found
 * ("absent"). Both are evidence the investigator wanted and did not have. */
export function missingFor(row: HypothesisRow): MissingItem[] {
  return row.predictions.flatMap((p): MissingItem[] =>
    p.state === "unknown"
      ? [{ prediction: p, kind: "unchecked" }]
      : p.state === "unmet"
        ? [{ prediction: p, kind: "absent" }]
        : [],
  );
}

/** DERIVED. The hypothesis the page opens on: the report's leader, else the first row. */
export function defaultHypothesis(rows: HypothesisRow[]): string | null {
  return (rows.find((r) => r.leading) ?? rows[0])?.hypothesis_id ?? null;
}

/** DERIVED. The reason the session stopped, in the investigator's own recorded words when it
 * stored them. Null when it never reached a stop. */
export function stoppedWhy(detail: Detail): string | null {
  for (const { event } of detail.timeline) {
    if (event.kind === "stopped") return event.why;
  }
  return null;
}
