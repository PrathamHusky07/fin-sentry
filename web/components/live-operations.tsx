"use client";

import { useEffect, useState } from "react";
import { CalibrationHealthPanel } from "@/components/calibration-health-panel";
import { MetricTile } from "@/components/metric-tile";
import { GATEWAY_URL } from "@/lib/config";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

type ConnectionState = "connecting" | "open" | "error";
type CalibrationFetchStatus = "loading" | "error" | "ready";

const DRIFT_STATE_COLOR: Record<string, string> = {
  healthy: "text-positive",
  degraded: "text-warning",
  drifted: "text-failure",
  unavailable: "text-failure",
  insufficient_data: "text-text-secondary",
};

/**
 * The real Day 9 Live Operations view: system health first, then the four
 * metric tiles the real materialized views actually carry, then the
 * calibration-health panel. Replaces the Day 8 raw <dl> connectivity probe.
 */
export function LiveOperations() {
  const [snapshot, setSnapshot] = useState<MetricsSnapshot | null>(null);
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("connecting");
  const [calibration, setCalibration] =
    useState<CalibrationHealthResponse | null>(null);
  const [calibrationStatus, setCalibrationStatus] =
    useState<CalibrationFetchStatus>("loading");
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const [calibrationRetryToken, setCalibrationRetryToken] = useState(0);

  useEffect(() => {
    const source = new EventSource(`${GATEWAY_URL}/ops/stream`);
    source.addEventListener("open", () => setConnectionState("open"));
    source.addEventListener("error", () => setConnectionState("error"));
    source.addEventListener("snapshot", (event: MessageEvent<string>) => {
      setSnapshot(JSON.parse(event.data) as MetricsSnapshot);
    });
    return () => source.close();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/calibration/health`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(
            `Calibration service unavailable — gateway returned ${res.status}`,
          );
        }
        return res.json() as Promise<CalibrationHealthResponse>;
      })
      .then((data) => {
        if (!cancelled) {
          setCalibration(data);
          setCalibrationStatus("ready");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCalibrationError(
            err instanceof Error
              ? err.message
              : "Calibration service unreachable.",
          );
          setCalibrationStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [calibrationRetryToken]);

  const throughput = snapshot?.throughput ?? null;
  const tokens = snapshot?.tokens ?? null;
  const cost = snapshot?.cost ?? null;
  const driftColor = calibration?.state
    ? (DRIFT_STATE_COLOR[calibration.state] ?? "text-text-secondary")
    : "text-text-secondary";

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <section
        aria-label="System health"
        className="border-border bg-background-elevated flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border p-4 text-sm"
      >
        <span className="font-semibold">System health</span>
        <span className="flex items-center gap-2">
          <span
            className={
              connectionState === "open"
                ? "bg-positive h-2 w-2 rounded-full"
                : connectionState === "error"
                  ? "bg-failure h-2 w-2 rounded-full"
                  : "bg-text-secondary h-2 w-2 rounded-full"
            }
          />
          SSE {connectionState === "open" ? "connected" : connectionState}
        </span>
        <span className="flex items-center gap-2">
          <span
            className={
              snapshot?.risingwave_connected
                ? "bg-positive h-2 w-2 rounded-full"
                : "bg-failure h-2 w-2 rounded-full"
            }
          />
          RisingWave{" "}
          {snapshot
            ? snapshot.risingwave_connected
              ? "connected"
              : "offline"
            : "unknown"}
        </span>
        <span
          className={`font-medium ${calibrationStatus === "error" ? "text-failure" : driftColor}`}
        >
          Drift:{" "}
          {calibrationStatus === "loading"
            ? "loading…"
            : calibrationStatus === "error"
              ? "unavailable"
              : (calibration?.state ?? "no reading persisted")}
        </span>
      </section>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
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

      {calibrationStatus === "error" ? (
        <div className="border-border bg-background-elevated mt-6 flex flex-wrap items-center gap-3 rounded-md border p-4">
          <p className="text-failure text-sm">{calibrationError}</p>
          <button
            type="button"
            onClick={() => {
              setCalibrationStatus("loading");
              setCalibrationRetryToken((n) => n + 1);
            }}
            className="border-border hover:bg-surface min-h-11 rounded-md border px-3 text-sm"
          >
            Retry
          </button>
        </div>
      ) : null}

      {calibrationStatus === "ready" && calibration ? (
        <div className="mt-6">
          <CalibrationHealthPanel health={calibration} />
        </div>
      ) : null}
    </div>
  );
}
