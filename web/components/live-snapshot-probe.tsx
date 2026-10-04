"use client";

import { useEffect, useState } from "react";
import { GATEWAY_URL } from "@/lib/config";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";

type ConnectionState = "connecting" | "open" | "error";

const STATE_LABEL: Record<ConnectionState, string> = {
  connecting: "Connecting…",
  open: "Connected",
  error: "Connection error (EventSource will retry)",
};

/**
 * Day 8 connectivity proof, not the Day 9 Live Operations UI: connects to
 * the gateway's real SSE snapshot relay and renders whatever it actually
 * sends, as plain typed values. No charts, no mock data, no setInterval
 * standing in for the stream -- if this shows numbers, a real snapshot
 * crossed the wire from real RisingWave data.
 */
export function LiveSnapshotProbe() {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");

  useEffect(() => {
    const source = new EventSource(`${GATEWAY_URL}/ops/stream`);

    source.addEventListener("open", () => setConnectionState("open"));
    source.addEventListener("error", () => setConnectionState("error"));
    source.addEventListener("snapshot", (event: MessageEvent<string>) => {
      setSnapshot(JSON.parse(event.data) as MetricsSnapshot);
    });

    return () => source.close();
  }, []);

  return (
    <div
      aria-live="polite"
      className="mt-8 w-full max-w-2xl rounded-lg border border-neutral-200 p-4 text-sm dark:border-neutral-800"
    >
      <p className="font-medium">
        SSE connectivity proof —{" "}
        <span
          className={
            connectionState === "open"
              ? "text-green-700 dark:text-green-400"
              : connectionState === "error"
                ? "text-red-700 dark:text-red-400"
                : "text-neutral-500"
          }
        >
          {STATE_LABEL[connectionState]}
        </span>
      </p>
      {snapshot ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-xs break-words">
          <dt className="text-neutral-500">generated_at</dt>
          <dd>{snapshot.generated_at}</dd>
          <dt className="text-neutral-500">risingwave_connected</dt>
          <dd>{String(snapshot.risingwave_connected)}</dd>
          <dt className="text-neutral-500">throughput</dt>
          <dd>{JSON.stringify(snapshot.throughput)}</dd>
          <dt className="text-neutral-500">faithfulness</dt>
          <dd>{JSON.stringify(snapshot.faithfulness)}</dd>
          <dt className="text-neutral-500">relevance</dt>
          <dd>{JSON.stringify(snapshot.relevance)}</dd>
          <dt className="text-neutral-500">tokens</dt>
          <dd>{JSON.stringify(snapshot.tokens)}</dd>
          <dt className="text-neutral-500">cost</dt>
          <dd>{JSON.stringify(snapshot.cost)}</dd>
          <dt className="text-neutral-500">frontier</dt>
          <dd>{JSON.stringify(snapshot.frontier)}</dd>
        </dl>
      ) : (
        <p className="mt-3 text-neutral-500">Waiting for the first snapshot…</p>
      )}
    </div>
  );
}
