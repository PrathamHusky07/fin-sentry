import { GATEWAY_URL } from "@/lib/config";
import {
  SCHEMA_RAIL_REASONS,
  type SchemaRailReason,
} from "@/lib/generation-bounds";
import type { TraceListItem, TraceListResponse } from "@/lib/trace-api";

/** Matches the backend's MAX_LIMIT, like the Overview scan. When the list returns exactly this
 * many, every count is a window over the newest requests and the page says so. */
const SCAN_LIMIT = 500;

export interface GenerationRecord {
  total: number;
  scanIsWindow: boolean;
  delivered: number;
  /** Requests that ended in an error status, such as an unreachable model. */
  errored: number;
  /** Replies the output schema rail rejected, by the reason it gave. */
  rejected: Record<SchemaRailReason, number>;
  /** The newest stored request for each reason that has one, so a count can be opened. */
  example: Partial<Record<SchemaRailReason, string>>;
  /** Ids of the newest delivered requests, newest first, from which an example is chosen. */
  recentDelivered: string[];
}

/** How many of the newest delivered requests are checked for one that cites its sources. */
export const EXAMPLE_CANDIDATES = 8;

/** Counts from the stored requests only. `traces` is newest first, as the gateway returns it. */
export function summarizeGeneration(
  traces: TraceListItem[],
  scanLimit: number = SCAN_LIMIT,
): GenerationRecord {
  const rejected = Object.fromEntries(
    SCHEMA_RAIL_REASONS.map((r) => [r, 0]),
  ) as Record<SchemaRailReason, number>;
  const example: GenerationRecord["example"] = {};
  const recentDelivered: string[] = [];
  let delivered = 0;
  let errored = 0;
  for (const t of traces) {
    if (t.rag_status === "success") {
      delivered += 1;
      if (recentDelivered.length < EXAMPLE_CANDIDATES) {
        recentDelivered.push(t.app_trace_id);
      }
    } else if (t.rag_status === "error") errored += 1;
    else if (t.rag_status === "blocked" && t.block_reason) {
      const reason = SCHEMA_RAIL_REASONS.find((r) => r === t.block_reason);
      if (reason) {
        rejected[reason] += 1;
        example[reason] ??= t.app_trace_id;
      }
    }
  }
  return {
    total: traces.length,
    scanIsWindow: traces.length >= scanLimit,
    delivered,
    errored,
    rejected,
    example,
    recentDelivered,
  };
}

/** Null means the fetch failed. The page then says the record is unavailable and shows no
 * count, so a failed read cannot pass for a clean history. */
export async function fetchGenerationRecord(): Promise<GenerationRecord | null> {
  try {
    const res = await fetch(`${GATEWAY_URL}/ops/traces?limit=${SCAN_LIMIT}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as TraceListResponse;
    return summarizeGeneration(body.traces);
  } catch {
    return null;
  }
}
