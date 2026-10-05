"use client";

import { useEffect, useState } from "react";
import { GATEWAY_URL } from "@/lib/config";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";

export type SseConnectionState = "connecting" | "open" | "error";

/**
 * Subscribes to the gateway's SSE snapshot relay (GET /ops/stream). Used by
 * both Live Operations and Overview, which both need the same real-time
 * metric tiles -- see ../CLAUDE.md's SSE semantics (full-state snapshots,
 * never a delta; EventSource reconnects on its own, no custom retry UI).
 */
export function useMetricsSnapshot(): {
  snapshot: MetricsSnapshot | null;
  connectionState: SseConnectionState;
} {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  const [connectionState, setConnectionState] =
    useState<SseConnectionState>("connecting");

  useEffect(() => {
    const source = new EventSource(`${GATEWAY_URL}/ops/stream`);
    source.addEventListener("open", () => setConnectionState("open"));
    source.addEventListener("error", () => setConnectionState("error"));
    source.addEventListener("snapshot", (event: MessageEvent<string>) => {
      setSnapshot(JSON.parse(event.data) as MetricsSnapshot);
    });
    return () => source.close();
  }, []);

  return { snapshot, connectionState };
}
