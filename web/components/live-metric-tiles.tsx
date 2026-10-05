"use client";

import { MetricTile } from "@/components/metric-tile";
import { StatusDot } from "@/components/status-dot";
import { useMetricsSnapshot } from "@/lib/use-metrics-snapshot";

/**
 * The real snapshot metrics (throughput, latency, tokens, cost) over SSE --
 * the one client-side island Overview needs, since there is no plain GET
 * snapshot proxy on the gateway (Option C: RisingWave access stays in the
 * dashboard process, the gateway only relays the poller's SSE stream).
 * Shared with Live Operations so both read the same live connection logic.
 */
export function LiveMetricTiles({
  showConnectionRow = false,
}: {
  showConnectionRow?: boolean;
}) {
  const { snapshot, connectionState } = useMetricsSnapshot();
  const throughput = snapshot?.throughput ?? null;
  const tokens = snapshot?.tokens ?? null;
  const cost = snapshot?.cost ?? null;

  return (
    <div>
      {showConnectionRow ? (
        <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className="flex items-center gap-2">
            <StatusDot
              color={
                connectionState === "open"
                  ? "positive"
                  : connectionState === "error"
                    ? "failure"
                    : "neutral"
              }
            />
            SSE {connectionState === "open" ? "connected" : connectionState}
          </span>
          <span className="flex items-center gap-2">
            <StatusDot
              color={snapshot?.risingwave_connected ? "positive" : "failure"}
            />
            RisingWave{" "}
            {snapshot
              ? snapshot.risingwave_connected
                ? "connected"
                : "offline"
              : "unknown"}
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          label="Throughput"
          value={throughput?.total_requests ?? null}
          unit="req"
          stale={throughput?.stale ?? true}
          asOf={throughput?.window_end ?? null}
        />
        <MetricTile
          label="Latency (avg / p95)"
          value={
            throughput?.avg_latency_ms != null &&
            throughput?.p95_latency_ms != null
              ? `${throughput.avg_latency_ms} / ${throughput.p95_latency_ms}`
              : null
          }
          unit="ms"
          stale={throughput?.stale ?? true}
          asOf={throughput?.window_end ?? null}
        />
        <MetricTile
          label="Token usage"
          value={
            tokens?.input_tokens_total != null &&
            tokens?.output_tokens_total != null
              ? tokens.input_tokens_total + tokens.output_tokens_total
              : null
          }
          unit="tok"
          stale={tokens?.stale ?? true}
          asOf={tokens?.window_end ?? null}
        />
        <MetricTile
          label="Cost"
          value={
            cost?.cost_total_usd != null
              ? `$${cost.cost_total_usd.toFixed(6)}`
              : null
          }
          stale={cost?.stale ?? true}
          asOf={cost?.window_end ?? null}
        />
      </div>
    </div>
  );
}
