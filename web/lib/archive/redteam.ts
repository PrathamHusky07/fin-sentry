import {
  asObject,
  bool,
  num,
  numOrNull,
  redTeamExecutions,
  redTeamRuns,
  scenariosYaml,
  str,
  strOrNull,
  ArchiveUnavailableError,
  type JsonObject,
} from "@/lib/archive/files";
import { micros, utcZ, utcZOrNull } from "@/lib/archive/time";
import { parseYamlSubset, type Yaml } from "@/lib/archive/yaml-subset";
import type {
  ExecutionList,
  ExecutionRecord,
  Expected,
  RunDetail,
  RunRecord,
  ScenarioList,
  ScenarioView,
} from "@/lib/red-team";

/**
 * The Red Team routes over the archived tables. A run is a row, an execution is a row, and the
 * run record's counts are derived from its executions the way finsentry/redteam/store.py derives
 * them. Rows were stored from model_dump output, so their fields are already complete.
 */

const MAX_PAGE = 100;

function execution(row: JsonObject): ExecutionRecord {
  // The stored row is passed through. Its JSON columns are already the model's own dump.
  return {
    execution_id: str(row, "execution_id"),
    run_id: str(row, "run_id"),
    seq: num(row, "seq"),
    scenario_id: str(row, "scenario_id"),
    scenario_version: num(row, "scenario_version"),
    category: str(row, "category") as ExecutionRecord["category"],
    target_layer: str(row, "target_layer"),
    mode: str(row, "mode") as ExecutionRecord["mode"],
    expected: asObject(row["expected"]) as unknown as Expected,
    state: str(row, "state") as ExecutionRecord["state"],
    outcome: strOrNull(row, "outcome") as ExecutionRecord["outcome"],
    acting_layer: strOrNull(row, "acting_layer"),
    acting_check: strOrNull(row, "acting_check"),
    expectation: strOrNull(
      row,
      "expectation",
    ) as ExecutionRecord["expectation"],
    reason: strOrNull(row, "reason"),
    evidence: asObject(row["evidence"]),
    trace_ref: strOrNull(row, "trace_ref"),
    gemini_calls: num(row, "gemini_calls"),
    cost_usd: num(row, "cost_usd"),
    started_at: utcZOrNull(strOrNull(row, "started_at")),
    finished_at: utcZOrNull(strOrNull(row, "finished_at")),
    duration_ms: numOrNull(row, "duration_ms"),
  };
}

function run(row: JsonObject, executions: JsonObject[]): RunRecord {
  const id = str(row, "run_id");
  const mine = executions.filter((e) => str(e, "run_id") === id);
  const outcomeCounts: Record<string, number> = {};
  // One count per (state, outcome) group, as the store's GROUP BY gives them.
  const groups = new Map<string, number>();
  for (const e of mine) {
    const key = JSON.stringify([str(e, "state"), strOrNull(e, "outcome")]);
    groups.set(key, (groups.get(key) ?? 0) + 1);
  }
  for (const [key, n] of groups) {
    const [, outcome] = JSON.parse(key) as [string, string | null];
    if (outcome !== null) outcomeCounts[outcome] = n;
  }
  const scenarioIds = row["scenario_ids"];
  if (!Array.isArray(scenarioIds)) {
    throw new ArchiveUnavailableError("archive run has no scenario list");
  }
  return {
    run_id: id,
    created_at: utcZ(str(row, "created_at")),
    finished_at: utcZOrNull(strOrNull(row, "finished_at")),
    status: str(row, "status") as RunRecord["status"],
    scenario_ids: scenarioIds.map(String),
    allow_judge_assisted: bool(row, "allow_judge_assisted"),
    failure_reason: strOrNull(row, "failure_reason"),
    total: mine.length,
    finished: mine.filter((e) => str(e, "state") === "finished").length,
    outcome_counts: outcomeCounts,
  };
}

const newestFirst = (a: JsonObject, b: JsonObject) =>
  micros(str(b, "created_at")) - micros(str(a, "created_at"));

export async function runList(limit: number): Promise<RunRecord[]> {
  const [runs, executions] = await Promise.all([
    redTeamRuns(),
    redTeamExecutions(),
  ]);
  return [...runs]
    .sort(newestFirst)
    .slice(0, limit)
    .map((r) => run(r, executions));
}

export async function runDetail(runId: string): Promise<RunDetail | null> {
  const [runs, executions] = await Promise.all([
    redTeamRuns(),
    redTeamExecutions(),
  ]);
  const row = runs.find((r) => str(r, "run_id") === runId);
  if (row === undefined) return null;
  return {
    run: run(row, executions),
    executions: executions
      .filter((e) => str(e, "run_id") === runId)
      .sort((a, b) => num(a, "seq") - num(b, "seq"))
      .map(execution),
  };
}

export interface ExecutionFilter {
  limit: number;
  offset: number;
  category: string | null;
  outcome: string | null;
  scenarioId: string | null;
  runId: string | null;
}

export async function executionList(
  f: ExecutionFilter,
): Promise<ExecutionList> {
  if (f.limit < 1 || f.limit > MAX_PAGE) {
    throw new RangeError(`limit must be between 1 and ${MAX_PAGE}`);
  }
  const [runs, executions] = await Promise.all([
    redTeamRuns(),
    redTeamExecutions(),
  ]);
  const created = new Map(
    runs.map((r) => [str(r, "run_id"), micros(str(r, "created_at"))]),
  );
  const rows = executions
    .filter((e) => f.category === null || str(e, "category") === f.category)
    .filter((e) => f.outcome === null || strOrNull(e, "outcome") === f.outcome)
    .filter(
      (e) => f.scenarioId === null || str(e, "scenario_id") === f.scenarioId,
    )
    .filter((e) => f.runId === null || str(e, "run_id") === f.runId)
    // The store joins each execution to its run, so one without a run row is not listed.
    .filter((e) => created.has(str(e, "run_id")))
    .sort(
      (a, b) =>
        (created.get(str(b, "run_id")) ?? 0) -
          (created.get(str(a, "run_id")) ?? 0) || num(a, "seq") - num(b, "seq"),
    )
    .slice(f.offset, f.offset + f.limit)
    .map(execution);
  return {
    executions: rows,
    next_offset: rows.length === f.limit ? f.offset + f.limit : null,
  };
}

export async function executionDetail(
  id: string,
): Promise<ExecutionRecord | null> {
  const row = (await redTeamExecutions()).find(
    (e) => str(e, "execution_id") === id,
  );
  return row === undefined ? null : execution(row);
}

type Obj = { [k: string]: Yaml };

function obj(value: Yaml | undefined, what: string): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ArchiveUnavailableError(`scenario ${what} is not a mapping`);
  }
  return value;
}

function text(value: Yaml | undefined, what: string): string {
  if (typeof value !== "string") {
    throw new ArchiveUnavailableError(`scenario ${what} is not text`);
  }
  return value;
}

/** The pydantic defaults the scenario models add, so the view has the same keys the gateway sends. */
function inputWithDefaults(
  executor: string,
  input: Obj,
): Record<string, unknown> {
  if (executor === "gateway_route") return { ticker: null, ...input };
  if (executor === "retrieval_rail") {
    const chunks = input["chunks"];
    if (!Array.isArray(chunks))
      throw new ArchiveUnavailableError("scenario chunks missing");
    return {
      ...input,
      chunks: chunks.map((c) => ({
        text: null,
        source_url: null,
        ...obj(c, "chunk"),
      })),
    };
  }
  if (executor === "output_rails") {
    return {
      ...input,
      payload_check: {
        value: null,
        ...obj(input["payload_check"], "payload check"),
      },
    };
  }
  return input;
}

export async function scenarioList(): Promise<ScenarioList> {
  const [yaml, executions] = await Promise.all([
    scenariosYaml(),
    redTeamExecutions(),
  ]);
  const parsed = parseYamlSubset(yaml);
  if (!Array.isArray(parsed))
    throw new ArchiveUnavailableError("scenario file is not a list");

  // The newest finished execution of each scenario, as latest_finished_per_scenario returns it.
  const latest = new Map<string, JsonObject>();
  for (const e of executions) {
    if (str(e, "state") !== "finished") continue;
    const id = str(e, "scenario_id");
    const held = latest.get(id);
    const at = micros(str(e, "finished_at"));
    if (held === undefined || at > micros(str(held, "finished_at")))
      latest.set(id, e);
  }

  const scenarios: ScenarioView[] = parsed.map((item) => {
    const s = obj(item, "entry");
    const executor = text(s["executor"], "executor");
    const last = latest.get(text(s["id"], "id"));
    return {
      id: text(s["id"], "id"),
      version: Number(s["version"]),
      title: text(s["title"], "title"),
      category: text(s["category"], "category") as ScenarioView["category"],
      target_layer: text(s["target_layer"], "target_layer"),
      description: text(s["description"], "description"),
      executor,
      mode: text(s["mode"], "mode") as ScenarioView["mode"],
      expected: {
        layer: null,
        check: null,
        known_gap: false,
        ...obj(s["expected"], "expected"),
      } as unknown as Expected,
      required_evidence: (s["required_evidence"] as string[]).map(String),
      severity: text(s["severity"], "severity") as ScenarioView["severity"],
      severity_rationale: text(s["severity_rationale"], "severity_rationale"),
      input: inputWithDefaults(executor, obj(s["input"], "input")),
      last_execution: last === undefined ? null : execution(last),
    };
  });
  return { scenarios, persistence_available: true };
}
