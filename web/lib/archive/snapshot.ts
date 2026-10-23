import {
  frontierVerdicts,
  judgeVerdicts,
  num,
  numOrNull,
  ragResponses,
  str,
  strOrNull,
  type JsonObject,
} from "@/lib/archive/files";
import { minuteStart } from "@/lib/archive/time";
import type {
  FaithfulnessMetrics,
  FrontierMetrics,
  JudgeCostMetrics,
  MetricsSnapshot,
  RelevanceMetrics,
  ThroughputMetrics,
  TokenUsageMetrics,
} from "@/lib/metrics-snapshot";

/**
 * The evaluation snapshot, rebuilt from the archived stream files with the definitions in
 * infra/risingwave/init.sql. Each section is the newest one-minute bucket that has data, which is
 * what the live dashboard reads from its materialized views. The buckets are the archive's own,
 * so their window ends are the original recording times, and every section is stale when read now.
 */

const MINUTE = 60_000;
/** Same rule as is_stale in finsentry/events/metrics_snapshot.py: older than two buckets. */
const STALE_AFTER = 2 * MINUTE;
const FRONTIER_WINDOW_MINUTES = 15;

const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");

function groupByMinute<T>(
  items: T[],
  at: (item: T) => string,
): Map<number, T[]> {
  const groups = new Map<number, T[]>();
  for (const item of items) {
    const key = minuteStart(at(item));
    const list = groups.get(key) ?? [];
    list.push(item);
    groups.set(key, list);
  }
  return groups;
}

function newestBucket<T>(groups: Map<number, T[]>): [number, T[]] | null {
  let best: [number, T[]] | null = null;
  for (const entry of groups)
    if (best === null || entry[0] > best[0]) best = entry;
  return best;
}

/** ROUND(x, places) as Postgres rounds numeric: halves go away from zero. */
function round(x: number, places: number): number {
  const f = 10 ** places;
  return Math.round(x * f) / f;
}

function mean(values: number[]): number | null {
  return values.length === 0
    ? null
    : values.reduce((a, b) => a + b, 0) / values.length;
}

/** AVG of integers rounded to one place, in integer arithmetic so a half never drifts. */
function meanRounded1(values: number[]): number | null {
  if (values.length === 0) return null;
  const sum = values.reduce((a, b) => a + b, 0);
  return Math.floor((20 * sum + values.length) / (2 * values.length)) / 10;
}

/** PERCENTILE_CONT(0.95): linear interpolation between the two nearest ranks. */
function percentile95(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = 0.95 * (sorted.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function present(values: (number | null)[]): number[] {
  return values.filter((v): v is number => v !== null);
}

function window(startMs: number) {
  return { window_start: iso(startMs), window_end: iso(startMs + MINUTE) };
}

const stale = (windowEndMs: number, now: number) =>
  now - windowEndMs > STALE_AFTER;

function throughput(rag: JsonObject[], now: number): ThroughputMetrics | null {
  const bucket = newestBucket(
    groupByMinute(rag, (r) => str(r, "timestamp_utc")),
  );
  if (bucket === null) return null;
  const [start, rows] = bucket;
  const latencies = present(rows.map((r) => numOrNull(r, "total_latency_ms")));
  const p95 = percentile95(latencies);
  const count = (status: string) =>
    rows.filter((r) => str(r, "status") === status).length;
  return {
    total_requests: rows.length,
    success_count: count("success"),
    blocked_count: count("blocked"),
    error_count: count("error"),
    avg_latency_ms: meanRounded1(latencies),
    p95_latency_ms: p95 === null ? null : round(p95, 1),
    ...window(start),
    stale: stale(start + MINUTE, now),
  };
}

function faithfulness(
  judge: JsonObject[],
  now: number,
): FaithfulnessMetrics | null {
  const scored = judge.filter(
    (j) => numOrNull(j, "faithfulness_score") !== null,
  );
  const bucket = newestBucket(
    groupByMinute(scored, (j) => str(j, "timestamp_utc")),
  );
  if (bucket === null) return null;
  const [start, rows] = bucket;
  const avg = mean(
    present(rows.map((j) => numOrNull(j, "faithfulness_score"))),
  );
  return {
    verdicts_count: rows.length,
    avg_faithfulness: avg === null ? null : round(avg, 3),
    complete_count: rows.filter(
      (j) => strOrNull(j, "faithfulness_status") === "complete",
    ).length,
    skipped_count: rows.filter((j) =>
      (strOrNull(j, "faithfulness_status") ?? "").startsWith("skipped_"),
    ).length,
    ...window(start),
    stale: stale(start + MINUTE, now),
  };
}

function relevance(judge: JsonObject[], now: number): RelevanceMetrics | null {
  const scored = judge.filter(
    (j) =>
      numOrNull(j, "answer_relevance_score") !== null ||
      numOrNull(j, "context_relevance_score") !== null,
  );
  const bucket = newestBucket(
    groupByMinute(scored, (j) => str(j, "timestamp_utc")),
  );
  if (bucket === null) return null;
  const [start, rows] = bucket;
  const answer = mean(
    present(rows.map((j) => numOrNull(j, "answer_relevance_score"))),
  );
  const context = mean(
    present(rows.map((j) => numOrNull(j, "context_relevance_score"))),
  );
  return {
    verdicts_count: rows.length,
    avg_answer_relevance: answer === null ? null : round(answer, 3),
    avg_context_relevance: context === null ? null : round(context, 3),
    ...window(start),
    stale: stale(start + MINUTE, now),
  };
}

function usage(
  judge: JsonObject[],
  now: number,
): { tokens: TokenUsageMetrics | null; cost: JudgeCostMetrics | null } {
  const bucket = newestBucket(
    groupByMinute(judge, (j) => str(j, "timestamp_utc")),
  );
  if (bucket === null) return { tokens: null, cost: null };
  const [start, rows] = bucket;
  const sum = (key: string) => rows.reduce((a, j) => a + num(j, key), 0);
  const costTotal = sum("total_cost_usd");
  const fresh = stale(start + MINUTE, now);
  return {
    tokens: {
      input_tokens_total: sum("total_input_tokens"),
      output_tokens_total: sum("total_output_tokens"),
      thoughts_tokens_total: sum("total_thoughts_tokens"),
      gemini_calls_total: sum("total_gemini_calls"),
      cost_total_usd: costTotal,
      ...window(start),
      stale: fresh,
    },
    cost: { cost_total_usd: costTotal, ...window(start), stale: fresh },
  };
}

/** The fifteen minutes the live dashboard sums are anchored to now. Here they are anchored to the
 * end of the newest archived bucket, because that is the last moment the archive has data for. */
function frontier(rows: JsonObject[], now: number): FrontierMetrics {
  const buckets = groupByMinute(rows, (f) => str(f, "evaluation_ts"));
  const newest = newestBucket(buckets);
  const verdictCounts: Record<string, number> = {};
  const disagreementCounts: Record<string, number> = {};
  if (newest !== null) {
    const cutoff = newest[0] + MINUTE - FRONTIER_WINDOW_MINUTES * MINUTE;
    for (const [start, list] of buckets) {
      if (start < cutoff) continue;
      for (const f of list) {
        const verdict = str(f, "verdict");
        const klass = str(f, "disagreement_classification");
        verdictCounts[verdict] = (verdictCounts[verdict] ?? 0) + 1;
        disagreementCounts[klass] = (disagreementCounts[klass] ?? 0) + 1;
      }
    }
  }
  const latestEnd = newest === null ? null : newest[0] + MINUTE;
  return {
    window_minutes: FRONTIER_WINDOW_MINUTES,
    verdict_counts: verdictCounts,
    disagreement_counts: disagreementCounts,
    latest_window_end: latestEnd === null ? null : iso(latestEnd),
    stale: latestEnd === null ? true : stale(latestEnd, now),
  };
}

export async function metricsSnapshot(
  nowMs: number = Date.now(),
): Promise<MetricsSnapshot> {
  const [rag, judge, front] = await Promise.all([
    ragResponses(),
    judgeVerdicts(),
    frontierVerdicts(),
  ]);
  const judgeRows = judge.map((r) => r.value);
  const { tokens, cost } = usage(judgeRows, nowMs);
  return {
    generated_at: new Date(nowMs).toISOString(),
    // No RisingWave behind this snapshot. It is read from the archived records.
    risingwave_connected: false,
    throughput: throughput(
      rag.map((r) => r.value),
      nowMs,
    ),
    faithfulness: faithfulness(judgeRows, nowMs),
    relevance: relevance(judgeRows, nowMs),
    tokens,
    cost,
    frontier: frontier(
      front.map((r) => r.value),
      nowMs,
    ),
  };
}
