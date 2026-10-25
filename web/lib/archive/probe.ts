import {
  gatewayProbeRuns,
  num,
  str,
  type JsonObject,
} from "@/lib/archive/files";
import { micros, utcZ } from "@/lib/archive/time";
import type {
  GatewayProbeRun,
  GatewayProbeSummary,
} from "@/lib/gateway-probe";

/**
 * GET /ops/gateway-probe/latest from the archived probe runs, in the live route's response shape:
 * the newest run and how many were recorded. The reading is the stored one with its original
 * recording time. No probe is run, and nothing is timed here.
 */

function toRun(row: JsonObject): GatewayProbeRun {
  return {
    measured_at: utcZ(str(row, "measured_at")),
    target: str(row, "target"),
    samples: num(row, "samples"),
    median_ms: num(row, "median_ms"),
    p95_ms: num(row, "p95_ms"),
    max_ms: num(row, "max_ms"),
  };
}

/** The newest run and the count, from the stored rows in any order. Newest recording time wins,
 * then the higher id, as latest_summary orders them in the gateway. */
export function latestFrom(rows: JsonObject[]): GatewayProbeSummary {
  const newest = [...rows].sort(
    (a, b) =>
      micros(str(b, "measured_at")) - micros(str(a, "measured_at")) ||
      num(b, "id") - num(a, "id"),
  )[0];
  return {
    latest: newest === undefined ? null : toRun(newest),
    runs_recorded: rows.length,
  };
}

export async function gatewayProbeLatest(): Promise<GatewayProbeSummary> {
  return latestFrom(await gatewayProbeRuns());
}
