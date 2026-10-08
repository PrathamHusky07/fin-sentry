import { StatusDot, type StatusColor } from "@/components/status-dot";
import { formatUtc, relativeTime } from "@/lib/format";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";
import type { SseConnectionState } from "@/lib/use-metrics-snapshot";

function age(ms: number | null, now: number | null): string {
  if (ms === null || now === null) return "waiting";
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  return seconds < 60
    ? `${seconds}s ago`
    : relativeTime(new Date(ms).toISOString(), now);
}

/** Which edge each cell's panel hangs from, so it stays inside the viewport:
 * the strip is two columns on a phone and four from lg up. */
const PEEK_SIDE = [
  "left-0",
  "right-0 lg:right-auto lg:left-0",
  "left-0",
  "right-0",
] as const;

interface Cell {
  label: string;
  value: string;
  /** What the value rests on, from state this component already holds. Shown
   * on hover and focus; nothing in it is new information. */
  detail: string;
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
      detail:
        connectionState === "open"
          ? `The browser holds an open EventSource to the gateway. ${receivedAt !== null ? `The last event arrived ${age(receivedAt, now)}.` : "No event has arrived yet."}`
          : connectionState === "connecting"
            ? "The browser is opening its EventSource to the gateway. No event has arrived yet."
            : "The connection dropped. The browser reconnects on its own, so the next snapshot is only delayed.",
    },
    {
      label: "Last snapshot",
      value: age(receivedAt, now),
      color: receivedAt === null ? "neutral" : "positive",
      detail: snapshot
        ? `Each snapshot is the full current state, not a change. The gateway generated this one at ${formatUtc(snapshot.generated_at)}. Age is measured on this browser's clock.`
        : "No snapshot has arrived. Each one is the full current state, not a change.",
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
      detail: snapshot
        ? snapshot.risingwave_connected
          ? "The gateway's metrics service could read RisingWave on its latest poll."
          : "The gateway's metrics service could not read RisingWave on its latest poll. Offline is a missing reading, not a quiet system."
        : "Waiting for the first snapshot to say whether RisingWave can be read.",
    },
    {
      label: "Metrics bucket",
      value: bucketEnd
        ? `${bucketStale ? "Stale, " : ""}ended ${age(new Date(bucketEnd).getTime(), now)}`
        : snapshot
          ? "No bucket"
          : "Waiting",
      color: bucketEnd ? (bucketStale ? "warning" : "positive") : "neutral",
      detail: bucketEnd
        ? `Latest one-minute bucket: ${formatUtc(snapshot?.throughput?.window_start ?? bucketEnd)} to ${formatUtc(bucketEnd)}. ${bucketStale ? "Stale means it ended more than two minutes ago, so no newer bucket has been produced." : "It ended within the last two minutes."}`
        : snapshot
          ? "The metrics view reported no bucket, which the gateway counts as stale."
          : "Waiting for the first snapshot.",
    },
  ];

  return (
    <div
      data-sticky-rail
      className="border-border bg-background/90 sticky top-[var(--nav-h)] z-30 border-b backdrop-blur"
    >
      <dl
        aria-label="Connection and freshness"
        className="mx-auto grid max-w-7xl grid-cols-2 gap-x-6 gap-y-0 px-4 py-1.5 sm:px-8 lg:grid-cols-4"
      >
        {cells.map((cell, i) => (
          <div
            key={cell.label}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Escape") e.currentTarget.blur();
            }}
            className="reveal-host hover:bg-surface-hover/70 relative -mx-2 flex min-h-11 items-center gap-2.5 rounded-lg px-2 transition-colors duration-[var(--dur-base)]"
          >
            <StatusDot color={cell.color} live={cell.live} />
            <dt className="text-text-tertiary text-sm">{cell.label}</dt>
            <dd className="text-text-primary text-sm font-medium">
              {cell.value}
            </dd>
            <dd
              className={`peek floating top-full mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-lg px-3.5 py-2.5 text-sm leading-snug font-normal ${PEEK_SIDE[i]}`}
            >
              <span className="text-text-secondary block">{cell.detail}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
