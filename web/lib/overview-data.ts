import { GATEWAY_URL } from "@/lib/config";
import type { ThroughputHistory } from "@/lib/metrics-snapshot";
import { blockStage, type BlockStage } from "@/lib/labels";
import type {
  CalibrationHealthResponse,
  TraceDetailResponse,
  TraceListItem,
  TraceListResponse,
} from "@/lib/trace-api";

/**
 * Server-side aggregation over the real trace list for Overview and Live
 * Operations. Matches the backend's MAX_LIMIT (finsentry/mcp/_util.py) --
 * one scan covers the whole real dataset at its current size. See
 * docs/internal/day9-frontend-data-contract.md for why this is a DERIVED
 * signal (counts from real persisted fields), not a new backend aggregate
 * endpoint. When the scan returns exactly the limit, every count here is a
 * window over the most recent executions, and `scanIsWindow` says so.
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

/** How far requests got, by rag_status and the stage that stopped them. */
export interface RequestFlow {
  total: number;
  stoppedAt: Record<BlockStage, number>;
  errored: number;
  delivered: number;
  /** The four ways a delivered answer can stand with the flash judge. These
   * always sum to `delivered`. */
  deliveredComplete: number;
  deliveredPartial: number;
  deliveredUnjudged: number;
  deliveredJudgeFailed: number;
}

export interface OverviewData {
  totalRequests: number;
  scanIsWindow: boolean;
  /** True when the disagreement query returned exactly its limit, so the
   * count is a floor over the most recent disagreements, not a total. */
  disagreementIsWindow: boolean;
  latestTimestamp: string | null;
  judgeStateCounts: JudgeStateCounts;
  flow: RequestFlow;
  frontierSampledCount: number;
  blockedTotal: number;
  blockedByReason: BlockReasonCount[];
  errorCount: number;
  disagreementTraces: TraceListItem[];
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

/** JSON-encoded so a ticker/query pair can never collide with another pair
 * whose concatenation happens to match. Kept with its test: it is the exact
 * key Overview used to group repeated questions before that list was cut. */
export function groupKey(trace: {
  ticker: string | null;
  query: string;
}): string {
  return JSON.stringify([trace.ticker, trace.query]);
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
  const flow: RequestFlow = {
    total: allTraces.length,
    stoppedAt: { input: 0, retrieval: 0, output: 0, unknown: 0 },
    errored: 0,
    delivered: 0,
    deliveredComplete: 0,
    deliveredPartial: 0,
    deliveredUnjudged: 0,
    deliveredJudgeFailed: 0,
  };
  const blockReasonTally = new Map<string, number>();
  let frontierSampledCount = 0;
  let latestMs = 0;

  for (const trace of allTraces) {
    judgeStateCounts[trace.judge_state] += 1;
    if (trace.frontier_sampled) frontierSampledCount += 1;
    latestMs = Math.max(latestMs, new Date(trace.timestamp_utc).getTime());

    if (trace.rag_status === "success") {
      flow.delivered += 1;
      if (trace.judge_state === "evaluated") flow.deliveredComplete += 1;
      else if (trace.judge_state === "partially_evaluated")
        flow.deliveredPartial += 1;
      else if (trace.judge_state === "judge_failed")
        flow.deliveredJudgeFailed += 1;
      else flow.deliveredUnjudged += 1;
    } else if (trace.rag_status === "error") {
      flow.errored += 1;
    } else if (trace.rag_status === "blocked" && trace.block_reason) {
      blockReasonTally.set(
        trace.block_reason,
        (blockReasonTally.get(trace.block_reason) ?? 0) + 1,
      );
      flow.stoppedAt[blockStage(trace.block_reason)] += 1;
    }
  }

  const blockedByReason = [...blockReasonTally.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count);
  const blockedTotal = blockedByReason.reduce((sum, r) => sum + r.count, 0);

  return {
    totalRequests: allTraces.length,
    scanIsWindow: allTraces.length >= STATS_SCAN_LIMIT,
    disagreementIsWindow: disagreementTraces.length >= STATS_SCAN_LIMIT,
    latestTimestamp: latestMs > 0 ? new Date(latestMs).toISOString() : null,
    judgeStateCounts,
    flow,
    frontierSampledCount,
    blockedTotal,
    blockedByReason,
    errorCount: flow.errored,
    disagreementTraces,
  };
}

/** The newest persisted executions, newest first (the gateway orders by
 * timestamp descending). Null means the fetch failed. */
export async function fetchRecentTraces(
  limit = 12,
): Promise<TraceListItem[] | null> {
  return fetchTraces({ limit: String(limit) });
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

/** One real trace's persisted detail, used to quote the actual flash and
 * frontier scores on an Overview attention item. Null when unavailable. */
export async function fetchTraceDetail(
  appTraceId: string,
): Promise<TraceDetailResponse | null> {
  try {
    const res = await fetch(`${GATEWAY_URL}/ops/traces/${appTraceId}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as TraceDetailResponse;
  } catch {
    return null;
  }
}

/** The latest persisted one-minute throughput buckets. Null means the fetch
 * failed -- the caller renders an honest "not available" state, never an
 * empty chart that could pass for a quiet system. */
export async function fetchThroughputHistory(
  limit = 60,
): Promise<ThroughputHistory | null> {
  try {
    const res = await fetch(
      `${GATEWAY_URL}/ops/metrics/throughput/history?limit=${limit}`,
      { cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as ThroughputHistory;
  } catch {
    return null;
  }
}
