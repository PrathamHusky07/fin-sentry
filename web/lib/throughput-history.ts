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
