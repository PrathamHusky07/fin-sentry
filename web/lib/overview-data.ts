import { GATEWAY_URL } from "@/lib/config";
import type {
  CalibrationHealthResponse,
  TraceListItem,
  TraceListResponse,
} from "@/lib/trace-api";

/**
 * Server-side aggregation over the real trace list for Overview and Live
 * Operations. Matches the backend's MAX_LIMIT (finsentry/mcp/_util.py) --
 * one scan covers the whole real dataset at its current size. See
 * docs/internal/day9-frontend-data-contract.md for why this is a DERIVED
 * signal (all-time counts from real persisted fields), not a new backend
 * aggregate endpoint.
 */
const STATS_SCAN_LIMIT = 500;

export interface JudgeStateCounts {
  evaluated: number;
  partially_evaluated: number;
  blocked_before_evaluation: number;
  judge_failed: number;
  never_evaluated: number;
}

export interface BlockReasonCount {
  reason: string;
  count: number;
}

export interface OverviewData {
  totalRequests: number;
  judgeStateCounts: JudgeStateCounts;
  frontierSampledCount: number;
  blockedTotal: number;
  blockedByReason: BlockReasonCount[];
  promptInjectionBlockedCount: number;
  disagreementTraces: TraceListItem[];
  recentInvestigations: TraceListItem[];
  recentChronological: TraceListItem[];
}

async function fetchTraces(
  params: Record<string, string>,
): Promise<TraceListItem[] | null> {
  try {
    const qs = new URLSearchParams({
      limit: String(STATS_SCAN_LIMIT),
      ...params,
    });
    const res = await fetch(`${GATEWAY_URL}/ops/traces?${qs.toString()}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as TraceListResponse;
    return body.traces;
  } catch {
    return null;
  }
}

function pickRecentInvestigations(
  allTraces: TraceListItem[],
  disagreementTraces: TraceListItem[],
  limit = 8,
): TraceListItem[] {
  const blocked = allTraces.filter((t) => t.rag_status === "blocked");
  const disagreementIds = new Set(
    disagreementTraces.map((t) => t.app_trace_id),
  );
  const others = allTraces.filter(
    (t) => t.rag_status !== "blocked" && !disagreementIds.has(t.app_trace_id),
  );

  const picked: TraceListItem[] = [];
  const seen = new Set<string>();
  for (const trace of [...disagreementTraces, ...blocked, ...others]) {
    if (seen.has(trace.app_trace_id)) continue;
    seen.add(trace.app_trace_id);
    picked.push(trace);
    if (picked.length >= limit) break;
  }
  return picked;
}

/** Null means the aggregate fetch failed -- callers render an honest
 * "not available right now" state, never a zeroed-out dashboard. */
export async function fetchOverviewData(): Promise<OverviewData | null> {
  const [allTraces, disagreementTraces] = await Promise.all([
    fetchTraces({}),
    fetchTraces({ disagreement: "true" }),
  ]);
  if (allTraces === null || disagreementTraces === null) return null;

  const judgeStateCounts: JudgeStateCounts = {
    evaluated: 0,
    partially_evaluated: 0,
    blocked_before_evaluation: 0,
    judge_failed: 0,
    never_evaluated: 0,
  };
  const blockReasonTally = new Map<string, number>();
  let promptInjectionBlockedCount = 0;
  let frontierSampledCount = 0;

  for (const trace of allTraces) {
    judgeStateCounts[trace.judge_state] += 1;
    if (trace.frontier_sampled) frontierSampledCount += 1;
    if (trace.rag_status === "blocked" && trace.block_reason) {
      blockReasonTally.set(
        trace.block_reason,
        (blockReasonTally.get(trace.block_reason) ?? 0) + 1,
      );
      if (trace.block_reason === "input_rail_blocked") {
        promptInjectionBlockedCount += 1;
      }
    }
  }

  const blockedByReason = [...blockReasonTally.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count);
  const blockedTotal = blockedByReason.reduce((sum, r) => sum + r.count, 0);

  return {
    totalRequests: allTraces.length,
    judgeStateCounts,
    frontierSampledCount,
    blockedTotal,
    blockedByReason,
    promptInjectionBlockedCount,
    disagreementTraces,
    recentInvestigations: pickRecentInvestigations(
      allTraces,
      disagreementTraces,
    ),
    recentChronological: allTraces.slice(0, 10),
  };
}

/** Null means the fetch failed -- the caller renders an honest absence
 * state, never a fabricated "healthy" reading. */
export async function fetchCalibrationHealth(): Promise<CalibrationHealthResponse | null> {
  try {
    const res = await fetch(`${GATEWAY_URL}/ops/calibration/health`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as CalibrationHealthResponse;
  } catch {
    return null;
  }
}
