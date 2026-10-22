import { formatUtc } from "@/lib/format";
import type { ThroughputBucket } from "@/lib/metrics-snapshot";

/** One bar of the persisted history. Built only from a stored bucket: nothing
 * is added for the minutes in between. */
export interface HistoryRow {
  key: string;
  /** Short axis label, UTC, e.g. "Oct 6 02:26". */
  label: string;
  /** Full span of the bucket, e.g. "Oct 6, 02:26 UTC to Oct 6, 02:27 UTC". */
  span: string;
  success: number;
  blocked: number;
  error: number;
  total: number;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
}

function axisLabel(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${month} ${d.getUTCDate()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

export function historyRows(buckets: ThroughputBucket[]): HistoryRow[] {
  return buckets.map((b) => ({
    key: b.window_start,
    label: axisLabel(b.window_start),
    span: `${formatUtc(b.window_start)} to ${formatUtc(b.window_end)}`,
    success: b.success_count,
    blocked: b.blocked_count,
    error: b.error_count,
    total: b.total_requests,
    avgLatencyMs: b.avg_latency_ms,
    p95LatencyMs: b.p95_latency_ms,
  }));
}

/** How many requests the shown buckets add up to, so the caption can say what
 * the bars cover. It is a sum of the shown buckets, not a platform total. */
export function historyRequestTotal(rows: HistoryRow[]): number {
  return rows.reduce((sum, r) => sum + r.total, 0);
}

/** How far back from the newest bucket the activity chart reaches. The
 * stored view can span days, and a chart that wide would shrink every
 * one-minute bar to a hairline. Anchored to the newest bucket, not to the
 * clock, so the same inputs always draw the same chart. */
export const ACTIVITY_WINDOW_MS = 60 * 60_000;

/** One bar of the activity chart. `stored` is a bucket the metrics view has
 * persisted. `live` is the one newest bucket, and only while the stream is
 * open and that bucket is fresh. Nothing else is ever called live. */
export interface ActivityBucket {
  windowEnd: string;
  totalRequests: number | null;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
  source: "stored" | "live";
}

/** A bucket as it arrived over the stream. Mirrors ThroughputHistoryPoint in
 * use-metrics-snapshot.ts, declared structurally so this module stays free of
 * the client hook. */
interface ReceivedBucket {
  windowEnd: string;
  totalRequests: number | null;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
}

/**
 * The activity chart's series: the stored buckets, then the buckets received
 * over the stream, merged on window_end so a bucket present in both is drawn
 * once. Where both sources hold the same bucket the received values win,
 * because they were read later. Minutes without a bucket stay absent: there
 * is no interpolation and no filling. The series is oldest first and limited
 * to ACTIVITY_WINDOW_MS ending at its newest bucket.
 *
 * `liveEdge` is the caller's claim that the stream is open and the newest
 * bucket is fresh. It is honored only when that newest bucket really arrived
 * over the stream, so a bucket known only from storage is never called live.
 */
export function mergeActivityBuckets(
  stored: ThroughputBucket[],
  received: ReceivedBucket[],
  liveEdge: boolean,
): ActivityBucket[] {
  const byTime = new Map<number, ActivityBucket>();
  for (const b of stored) {
    byTime.set(new Date(b.window_end).getTime(), {
      windowEnd: b.window_end,
      totalRequests: b.total_requests,
      avgLatencyMs: b.avg_latency_ms,
      p95LatencyMs: b.p95_latency_ms,
      source: "stored",
    });
  }
  let newestReceived = -Infinity;
  for (const r of received) {
    const t = new Date(r.windowEnd).getTime();
    newestReceived = Math.max(newestReceived, t);
    byTime.set(t, { ...r, source: "stored" });
  }

  const times = [...byTime.keys()].sort((a, b) => a - b);
  if (times.length === 0) return [];
  const newest = times[times.length - 1];
  const series: ActivityBucket[] = [];
  for (const t of times) {
    const bucket = byTime.get(t);
    if (!bucket || t < newest - ACTIVITY_WINDOW_MS) continue;
    series.push(
      liveEdge && t === newest && t === newestReceived
        ? { ...bucket, source: "live" }
        : bucket,
    );
  }
  return series;
}

/** A bucket older than this is stale: the backend's own rule (two bucket widths,
 * finsentry/events/metrics_snapshot.py) and the wording the connection strip uses. */
export const STALE_AFTER_MS = 2 * 60_000;

/** What the activity series is, judged against the clock. `unknown` is the server render and
 * the first client render, before a clock exists, so nothing is claimed about recency yet.
 * `last-recorded` means the newest stored bucket is stale, so the series is the last activity
 * that was recorded and not the last hour of the clock. */
export type ActivityScope =
  | { kind: "unknown" }
  | { kind: "none" }
  | { kind: "current" }
  | { kind: "last-recorded"; endedAt: string; ageMs: number };

export function activityScope(
  buckets: ActivityBucket[],
  nowMs: number | null,
): ActivityScope {
  if (buckets.length === 0) return { kind: "none" };
  if (nowMs === null) return { kind: "unknown" };
  const endedAt = buckets[buckets.length - 1].windowEnd;
  const ageMs = nowMs - new Date(endedAt).getTime();
  return ageMs > STALE_AFTER_MS
    ? { kind: "last-recorded", endedAt, ageMs }
    : { kind: "current" };
}
