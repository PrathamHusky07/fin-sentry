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
  detail: string;
  color: StatusColor;
}

/**
 * Four freshness readings in one band: is the stream connected, when the
 * last snapshot arrived, whether the gateway can reach RisingWave, and how
 * old the metrics bucket itself is. They are separate facts. A stream can be
 * connected while the underlying bucket is hours old, and the band shows
 * both instead of one green light.
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
      detail: "Server-Sent Events from the gateway",
      color:
        connectionState === "open"
          ? "positive"
          : connectionState === "error"
            ? "failure"
            : "neutral",
    },
    {
      label: "Last snapshot",
      value: age(receivedAt, now),
      detail: "The gateway pushes full state every 3 seconds",
      color: receivedAt === null ? "neutral" : "positive",
    },
    {
      label: "RisingWave",
      value: snapshot
        ? snapshot.risingwave_connected
          ? "Reachable"
          : "Offline"
        : "Waiting",
      detail: "As seen by the dashboard service",
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
      detail: "Latest one-minute window in the throughput view",
      color: bucketEnd ? (bucketStale ? "warning" : "positive") : "neutral",
    },
  ];

  return (
    <dl className="divide-border border-border grid grid-cols-1 divide-y border-y sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
      {cells.map((cell) => (
        <div
          key={cell.label}
          className="px-1 py-4 sm:px-5 sm:first:pl-0 lg:first:pl-0"
        >
          <dt className="eyebrow">{cell.label}</dt>
          <dd className="mt-2 flex items-center gap-2.5">
            <StatusDot color={cell.color} />
            <span className="text-text-primary text-lg font-medium">
              {cell.value}
            </span>
          </dd>
          <dd className="text-text-tertiary mt-1 text-sm">{cell.detail}</dd>
        </div>
      ))}
    </dl>
  );
}
