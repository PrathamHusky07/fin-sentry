"use client";

import { useEffect, useState } from "react";
import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { GATEWAY_URL } from "@/lib/config";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";
import { opsFetch } from "@/lib/ops-fetch";

export type SseConnectionState = "connecting" | "open" | "error";

/**
 * Subscribes to the gateway's SSE snapshot relay (GET /ops/stream), used
 * by Live Operations -- see ../CLAUDE.md's SSE semantics (full-state snapshots,
 * never a delta; EventSource reconnects on its own, no custom retry UI).
 *
 * In archived-evidence mode there is no stream. The hook reads the one archived snapshot once,
 * with its original window times and stale flags, and opens no EventSource.
 *
 * `connectionState` is not shown as a status. The page reads it for one thing: telling
 * "the stream has not answered" apart from "it answered and a window was empty", so an
 * unreachable gateway shows as unavailable and never as a quiet system.
 */
export function useMetricsSnapshot(): {
  snapshot: MetricsSnapshot | null;
  connectionState: SseConnectionState;
} {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  const [connectionState, setConnectionState] =
    useState<SseConnectionState>("connecting");

  useEffect(() => {
    if (ARCHIVE_MODE) {
      let cancelled = false;
      opsFetch("/ops/metrics/snapshot")
        .then((res) => {
          if (!res.ok) throw new Error(`archive answered ${res.status}`);
          return res.json() as Promise<MetricsSnapshot>;
        })
        .then((data) => {
          if (cancelled) return;
          setSnapshot(data);
          setConnectionState("open");
        })
        .catch(() => {
          if (!cancelled) setConnectionState("error");
        });
      return () => {
        cancelled = true;
      };
    }
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
