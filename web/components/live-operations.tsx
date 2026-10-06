"use client";

import { useEffect, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { CalibrationHealthPanel } from "@/components/calibration-health-panel";
import { JudgeStateDistribution } from "@/components/judge-state-distribution";
import { LiveMetricTiles } from "@/components/live-metric-tiles";
import { Panel } from "@/components/panel";
import { RecentActivityChart } from "@/components/recent-activity-chart";
import { RecentTraces } from "@/components/recent-traces";
import { StatusDot } from "@/components/status-dot";
import { GATEWAY_URL } from "@/lib/config";
import type { OverviewData } from "@/lib/overview-data";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

const DRIFT_STATE_COLOR: Record<
  string,
  "positive" | "warning" | "failure" | "neutral"
> = {
  healthy: "positive",
  degraded: "warning",
  drifted: "failure",
  unavailable: "failure",
  insufficient_data: "neutral",
};

/**
 * What is happening right now: real snapshot metrics with staleness, the
 * calibration panel, operational signals derived from the full real trace
 * list, and a small chronological recent-activity list -- never the full
 * trace dump (that's Investigations).
 */
export function LiveOperations({
  overviewData,
}: {
  overviewData: OverviewData | null;
}) {
  const [calibration, setCalibration] =
    useState<CalibrationHealthResponse | null>(null);
  const [calibrationStatus, setCalibrationStatus] =
    useState<AsyncStatus>("loading");
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const [calibrationRetryToken, setCalibrationRetryToken] = useState(0);

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

  const driftColor =
    calibrationStatus === "error"
      ? "failure"
      : calibration?.state
        ? (DRIFT_STATE_COLOR[calibration.state] ?? "neutral")
        : "neutral";

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-text-primary text-3xl font-semibold tracking-tight">
        Live Operations
      </h1>
      <p className="text-text-secondary mt-1.5 max-w-2xl text-sm">
        What is happening right now: real snapshot metrics with staleness,
        calibration drift, and recent activity. Not the full trace dump -- that
        is Investigations.
      </p>

      <section
        aria-label="System health"
        className="border-border bg-background-elevated mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border p-4 text-sm"
      >
        <span className="font-semibold">System health</span>
        <span className={`flex items-center gap-2`}>
          <StatusDot color={driftColor} />
          Drift:{" "}
          {calibrationStatus === "loading"
            ? "loading…"
            : calibrationStatus === "error"
              ? "unavailable"
              : (calibration?.state ?? "no reading persisted")}
        </span>
      </section>

      <div className="mt-6">
        <LiveMetricTiles showConnectionRow>
          {(history) => <RecentActivityChart history={history} />}
        </LiveMetricTiles>
      </div>

      <div className="mt-6">
        <AsyncState
          status={calibrationStatus}
          errorMessage={calibrationError}
          onRetry={() => {
            setCalibrationStatus("loading");
            setCalibrationRetryToken((n) => n + 1);
          }}
        >
          {calibration ? <CalibrationHealthPanel health={calibration} /> : null}
        </AsyncState>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {overviewData ? (
          <JudgeStateDistribution counts={overviewData.judgeStateCounts} />
        ) : (
          <Panel className="p-4">
            <h2 className="text-text-primary text-sm font-semibold">
              Judge-state distribution
            </h2>
            <p className="text-failure mt-3 text-sm">
              Trace service unavailable -- counts could not be loaded.
            </p>
          </Panel>
        )}

        <Panel className="p-4">
          <h2 className="text-text-primary text-sm font-semibold">
            Blocked requests
          </h2>
          {overviewData ? (
            <>
              <p className="text-text-secondary mt-1 text-xs">
                {overviewData.blockedTotal} blocked, all-time.
              </p>
              <ul className="mt-3 flex flex-col gap-1.5">
                {overviewData.blockedByReason.map((r) => (
                  <li
                    key={r.reason}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="text-text-secondary">{r.reason}</span>
                    <span className="tabular-metric text-text-primary">
                      {r.count}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-failure mt-3 text-sm">
              Trace service unavailable -- counts could not be loaded.
            </p>
          )}
        </Panel>
      </div>

      <div className="mt-6">
        <RecentTraces
          title="Recent activity"
          description="The most recent real traces, in order. Repeated questions are grouped; every real execution is still visible in Investigations."
          groups={overviewData?.recentChronological ?? []}
        />
      </div>
    </div>
  );
}
