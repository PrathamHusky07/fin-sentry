import { GATEWAY_URL } from "@/lib/config";
import type {
  ExecutionList,
  ExecutionRecord,
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

/** Whether the gateway has a run password configured. When it does not, every run is refused,
 * so the page says runs are disabled instead of asking for a password. */
export const fetchRunGate = () =>
  call<{ runs_enabled?: unknown }>("/run-gate").then((g) =>
    typeof g.runs_enabled === "boolean" ? g.runs_enabled : null,
  );

/** Starts a run. The password goes in a request header, never in the URL or the body, and the
 * gateway checks it before anything is created. The page never stores it. */
export const startRun = (
  scenarioIds: string[] | null,
  allowJudge: boolean,
  password: string,
) =>
  call<RunDetail>("/runs", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-run-password": password,
    },
    body: JSON.stringify({
      scenario_ids: scenarioIds,
      allow_judge_assisted: allowJudge,
    }),
  });

/** The most executions the console loads for history. The API returns newest first, so a
 * longer history keeps the newest and the page says it was cut. */
export const MAX_LOADED_EXECUTIONS = 500;

export interface LoadedExecutions {
  executions: ExecutionRecord[];
  truncated: boolean;
}

/** Every stored execution, page by page, newest first. The history, the streaks and the
 * regressions are derived from this one read, so the console never shows a count that a
 * second fetch could contradict. */
export async function fetchAllExecutions(): Promise<LoadedExecutions> {
  const executions: ExecutionRecord[] = [];
  let offset = 0;
  while (executions.length < MAX_LOADED_EXECUTIONS) {
    const page = await call<ExecutionList>(
      `/executions?limit=100&offset=${offset}`,
    );
    executions.push(...page.executions);
    if (page.next_offset === null) return { executions, truncated: false };
    offset = page.next_offset;
  }
  return { executions, truncated: true };
}
