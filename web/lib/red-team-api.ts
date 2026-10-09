import { GATEWAY_URL } from "@/lib/config";
import type {
  Category,
  ExecutionList,
  ExecutionRecord,
  Outcome,
  RunDetail,
  RunRecord,
  ScenarioList,
} from "@/lib/red-team";

/** A failed Red Team API call. `activeRunId` is set on the 409 that says a run
 * is already in progress, so the console can follow that run instead. */
export class RedTeamApiError extends Error {
  readonly status: number;
  readonly activeRunId: string | null;

  constructor(message: string, status: number, activeRunId: string | null) {
    super(message);
    this.status = status;
    this.activeRunId = activeRunId;
  }
}

function field(body: unknown, key: string): unknown {
  return typeof body === "object" && body !== null
    ? (body as Record<string, unknown>)[key]
    : undefined;
}

function messageFor(body: unknown, status: number): string {
  const error = field(body, "error");
  if (typeof error === "string") return error;
  if (Array.isArray(field(body, "detail"))) {
    return "The request was not valid.";
  }
  return `The gateway returned ${status}.`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${GATEWAY_URL}/ops/redteam${path}`, init);
  } catch {
    throw new RedTeamApiError("The gateway could not be reached.", 0, null);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const runId = field(body, "run_id");
    throw new RedTeamApiError(
      messageFor(body, res.status),
      res.status,
      typeof runId === "string" ? runId : null,
    );
  }
  return body as T;
}

export const fetchScenarios = () => call<ScenarioList>("/scenarios");

export const fetchRuns = (limit = 20) =>
  call<RunRecord[]>(`/runs?limit=${limit}`);

export const fetchRun = (runId: string) => call<RunDetail>(`/runs/${runId}`);

export const fetchExecution = (executionId: string) =>
  call<ExecutionRecord>(`/executions/${executionId}`);

export interface ExecutionFilters {
  category: Category | "";
  outcome: Outcome | "";
  runId: string;
}

export function fetchExecutions(
  filters: ExecutionFilters,
  offset: number,
  limit = 25,
) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (filters.category) params.set("category", filters.category);
  if (filters.outcome) params.set("outcome", filters.outcome);
  if (filters.runId) params.set("run_id", filters.runId);
  return call<ExecutionList>(`/executions?${params.toString()}`);
}

export const startRun = (scenarioIds: string[] | null, allowJudge: boolean) =>
  call<RunDetail>("/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      scenario_ids: scenarioIds,
      allow_judge_assisted: allowJudge,
    }),
  });
