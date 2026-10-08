"use client";

import { useEffect, useState } from "react";
import { GATEWAY_URL } from "@/lib/config";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";

export type SseConnectionState = "connecting" | "open" | "error";

/** One real throughput bucket as it arrived live over SSE. LIVE provenance
 * -- never backfilled. This accumulates client-side from the snapshots that
 * actually arrived while the page was open. Stored buckets come separately
 * from GET /ops/metrics/throughput/history and are drawn by their own panel,
 * so the two are never merged into one series. */
export interface ThroughputHistoryPoint {
  windowEnd: string;
  totalRequests: number | null;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
}

const MAX_HISTORY_POINTS = 60;

/**
 * Subscribes to the gateway's SSE snapshot relay (GET /ops/stream), used
 * by Live Operations -- see ../CLAUDE.md's SSE semantics (full-state snapshots,
 * never a delta; EventSource reconnects on its own, no custom retry UI).
 *
 * Also accumulates `throughputHistory`: the poller pushes a snapshot every
 * 3 seconds (finsentry/gateway/metrics_poller.py) but the underlying
 * materialized view only advances once a real minute -- a new point is
 * recorded only when `window_end` actually changes, deduping the ~20
 * identical pushes per bucket, capped at the last 60 distinct buckets.
 */
export function useMetricsSnapshot(): {
  snapshot: MetricsSnapshot | null;
  /** Browser clock time (ms) the latest snapshot arrived, for freshness. */
  receivedAt: number | null;
  connectionState: SseConnectionState;
  throughputHistory: ThroughputHistoryPoint[];
} {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  const [receivedAt, setReceivedAt] = useState<number | null>(null);
  const [connectionState, setConnectionState] =
    useState<SseConnectionState>("connecting");
  const [throughputHistory, setThroughputHistory] = useState<
    ThroughputHistoryPoint[]
  >([]);

  useEffect(() => {
    const source = new EventSource(`${GATEWAY_URL}/ops/stream`);
    source.addEventListener("open", () => setConnectionState("open"));
    source.addEventListener("error", () => setConnectionState("error"));
    source.addEventListener("snapshot", (event: MessageEvent<string>) => {
      const next = JSON.parse(event.data) as MetricsSnapshot;
      setSnapshot(next);
      setReceivedAt(Date.now());

      const windowEnd = next.throughput?.window_end;
      if (!windowEnd) return;
      setThroughputHistory((prev) => {
        if (prev.length > 0 && prev[prev.length - 1].windowEnd === windowEnd) {
          return prev;
        }
        const point: ThroughputHistoryPoint = {
          windowEnd,
          totalRequests: next.throughput?.total_requests ?? null,
          avgLatencyMs: next.throughput?.avg_latency_ms ?? null,
          p95LatencyMs: next.throughput?.p95_latency_ms ?? null,
        };
        const updated = [...prev, point];
        return updated.length > MAX_HISTORY_POINTS
          ? updated.slice(-MAX_HISTORY_POINTS)
          : updated;
      });
    });
    return () => source.close();
  }, []);

  return { snapshot, receivedAt, connectionState, throughputHistory };
}
