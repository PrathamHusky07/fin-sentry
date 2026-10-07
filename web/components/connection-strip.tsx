import { StatusDot, type StatusColor } from "@/components/status-dot";
import { relativeTime } from "@/lib/format";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";
import type { SseConnectionState } from "@/lib/use-metrics-snapshot";

function age(ms: number | null, now: number | null): string {
  if (ms === null || now === null) return "waiting";
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  return seconds < 60
    ? `${seconds}s ago`
    : relativeTime(new Date(ms).toISOString(), now);
}

interface Cell {
  label: string;
  value: string;
  color: StatusColor;
  /** Only the open stream pulses: it is the one claim of liveness here. */
  live?: boolean;
}

/**
 * The freshness band. Four separate facts in one pinned line: is the stream
 * connected, when the last snapshot arrived, whether the gateway can reach
 * RisingWave, and how old the metrics bucket itself is. A stream can be
 * connected while the bucket is hours old, and the band shows both instead
 * of one green light. It stays pinned under the nav so freshness is in view
 * whatever is scrolled into the page.
 */
export function ConnectionStrip({
  connectionState,
  snapshot,
  receivedAt,
  now,
}: {
  connectionState: SseConnectionState;
  snapshot: MetricsSnapshot | null;
  receivedAt: number | null;
  now: number | null;
}) {
  const bucketEnd = snapshot?.throughput?.window_end ?? null;
  const bucketStale = snapshot?.throughput?.stale ?? null;

  const cells: Cell[] = [
    {
      label: "Stream",
      value:
        connectionState === "open"
          ? "Connected"
          : connectionState === "connecting"
            ? "Connecting"
            : "Reconnecting",
      color:
        connectionState === "open"
          ? "positive"
          : connectionState === "error"
            ? "failure"
            : "neutral",
      live: connectionState === "open",
    },
    {
      label: "Last snapshot",
      value: age(receivedAt, now),
      color: receivedAt === null ? "neutral" : "positive",
    },
    {
      label: "RisingWave",
      value: snapshot
        ? snapshot.risingwave_connected
          ? "Reachable"
          : "Offline"
        : "Waiting",
      color: snapshot
        ? snapshot.risingwave_connected
          ? "positive"
          : "failure"
        : "neutral",
    },
    {
      label: "Metrics bucket",
      value: bucketEnd
        ? `${bucketStale ? "Stale, " : ""}ended ${age(new Date(bucketEnd).getTime(), now)}`
        : snapshot
          ? "No bucket"
          : "Waiting",
      color: bucketEnd ? (bucketStale ? "warning" : "positive") : "neutral",
    },
  ];

  return (
    <div className="border-border bg-background/90 sticky top-[var(--nav-h)] z-30 border-b backdrop-blur">
      <dl
        aria-label="Connection and freshness"
        className="mx-auto grid max-w-7xl grid-cols-2 gap-x-6 gap-y-1 px-4 py-2.5 sm:px-8 lg:grid-cols-4"
      >
        {cells.map((cell) => (
          <div key={cell.label} className="flex min-h-9 items-center gap-2.5">
            <StatusDot color={cell.color} live={cell.live} />
            <dt className="text-text-tertiary text-sm">{cell.label}</dt>
            <dd className="text-text-primary text-sm font-medium">
              {cell.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
