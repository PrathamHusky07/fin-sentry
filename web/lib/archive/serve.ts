import "server-only";
import { calibrationHealth } from "@/lib/archive/calibration";
import { ArchiveUnavailableError } from "@/lib/archive/files";
import {
  investigationDetail,
  investigationList,
} from "@/lib/archive/investigations";
import {
  executionDetail,
  executionList,
  runDetail,
  runList,
  scenarioList,
} from "@/lib/archive/redteam";
import { metricsSnapshot } from "@/lib/archive/snapshot";
import { JUDGE_STATES, traceDetail, traceList } from "@/lib/archive/traces";
import type { JudgeState } from "@/lib/trace-api";

/**
 * The read-only routes archived-evidence mode answers. Paths are the gateway's own /ops paths, so
 * a caller needs no second set of names. Each answer is the gateway's response shape for that
 * route. A route with no archived source is not listed here and answers 404, never an empty body.
 * Only GET is ever dispatched, so nothing here can start work.
 */

class BadRequest extends Error {}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function failure(status: number, message: string): Response {
  return json({ error: message }, status);
}

function intParam(
  params: URLSearchParams,
  key: string,
  fallback: number,
): number {
  const raw = params.get(key);
  if (raw === null) return fallback;
  if (!/^-?\d+$/.test(raw)) throw new BadRequest(`${key} must be an integer`);
  return Number(raw);
}

function boolParam(params: URLSearchParams, key: string): boolean | null {
  const raw = params.get(key);
  if (raw === null) return null;
  if (raw === "true" || raw === "1") return true;
  if (raw === "false" || raw === "0") return false;
  throw new BadRequest(`${key} must be true or false`);
}

function judgeStateParam(params: URLSearchParams): JudgeState | null {
  const raw = params.get("judge_state");
  if (raw === null) return null;
  const state = JUDGE_STATES.find((s) => s === raw);
  if (state === undefined)
    throw new BadRequest("judge_state is not a known state");
  return state;
}

function notFound(what: string): Response {
  return failure(404, `${what} not found`);
}

async function route(
  segments: string[],
  params: URLSearchParams,
): Promise<Response> {
  const [head, second, third] = segments;

  if (head === "traces" && segments.length === 1) {
    return json(
      await traceList({
        limit: intParam(params, "limit", 50),
        offset: intParam(params, "offset", 0),
        ticker: params.get("ticker"),
        status: params.get("status"),
        q: params.get("q"),
        judgeState: judgeStateParam(params),
        frontierSampled: boolParam(params, "frontier_sampled"),
        disagreement: boolParam(params, "disagreement"),
      }),
    );
  }
  if (head === "traces" && segments.length === 2) {
    return json(await traceDetail(decodeURIComponent(second)));
  }
  if (head === "calibration" && second === "health" && segments.length === 2) {
    return json(await calibrationHealth());
  }
  if (head === "metrics" && second === "snapshot" && segments.length === 2) {
    return json(await metricsSnapshot());
  }

  if (head === "investigations" && segments.length === 1) {
    return json(
      await investigationList({
        limit: intParam(params, "limit", 20),
        offset: intParam(params, "offset", 0),
        status: params.get("status"),
      }),
    );
  }
  if (head === "investigations" && segments.length === 2) {
    const found = await investigationDetail(decodeURIComponent(second));
    return found === null ? notFound("investigation") : json(found);
  }

  if (head === "redteam") {
    if (second === "scenarios" && segments.length === 2)
      return json(await scenarioList());
    // Runs are never enabled on archived evidence. This is a fact about the mode, not a reading.
    if (second === "run-gate" && segments.length === 2)
      return json({ runs_enabled: false });
    if (second === "runs" && segments.length === 2) {
      return json(
        await runList(Math.min(Math.max(intParam(params, "limit", 20), 1), 50)),
      );
    }
    if (second === "runs" && segments.length === 3) {
      const found = await runDetail(decodeURIComponent(third));
      return found === null ? notFound("run") : json(found);
    }
    if (second === "executions" && segments.length === 2) {
      return json(
        await executionList({
          limit: intParam(params, "limit", 50),
          offset: intParam(params, "offset", 0),
          category: params.get("category"),
          outcome: params.get("outcome"),
          scenarioId: params.get("scenario_id"),
          runId: params.get("run_id"),
        }),
      );
    }
    if (second === "executions" && segments.length === 3) {
      const found = await executionDetail(decodeURIComponent(third));
      return found === null ? notFound("execution") : json(found);
    }
  }

  return failure(404, "this route has no archived record");
}

/** `path` is a gateway-style path such as `/ops/traces?limit=5`. */
export async function serveArchive(path: string): Promise<Response> {
  const url = new URL(path, "http://archive.invalid");
  const segments = url.pathname.split("/").filter((s) => s !== "");
  if (segments[0] !== "ops")
    return failure(404, "this route has no archived record");
  try {
    return await route(segments.slice(1), url.searchParams);
  } catch (error: unknown) {
    if (error instanceof BadRequest || error instanceof RangeError) {
      return failure(422, error.message);
    }
    if (error instanceof ArchiveUnavailableError) {
      return failure(503, "the archived record could not be read");
    }
    throw error;
  }
}
