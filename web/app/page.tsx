import type { Metadata } from "next";
import { AttentionRequired } from "@/components/attention-required";
import { JudgeStateDistribution } from "@/components/judge-state-distribution";
import { LiveMetricTiles } from "@/components/live-metric-tiles";
import { Panel } from "@/components/panel";
import { RecentTraces } from "@/components/recent-traces";
import { ReliabilityPipeline } from "@/components/reliability-pipeline";
import { StatusDot } from "@/components/status-dot";
import { fetchCalibrationHealth, fetchOverviewData } from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Overview — Fin-Sentry",
};

const CALIBRATION_STATE_COLOR: Record<
  string,
  "positive" | "warning" | "failure"
> = {
  healthy: "positive",
  degraded: "warning",
  drifted: "failure",
  unavailable: "failure",
};

export default async function OverviewPage() {
  const [overview, calibration] = await Promise.all([
    fetchOverviewData(),
    fetchCalibrationHealth(),
  ]);

  const evaluatedCount = overview
    ? overview.judgeStateCounts.evaluated +
      overview.judgeStateCounts.partially_evaluated
    : null;
  const evaluationCompletionPct =
    overview && overview.totalRequests > 0 && evaluatedCount !== null
      ? ((evaluatedCount / overview.totalRequests) * 100).toFixed(1)
      : null;

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-text-primary text-2xl font-semibold tracking-tight">
        Overview
      </h1>
      <p className="text-text-secondary mt-1 text-sm">
        Is the platform healthy, what needs attention, and why.
      </p>

      <section
        aria-label="System status"
        className="border-border bg-background-elevated mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-md border p-4 text-sm"
      >
        <span className="font-semibold">System status</span>
        <span className="flex items-center gap-2">
          <StatusDot
            color={
              calibration
                ? (CALIBRATION_STATE_COLOR[calibration.state ?? ""] ??
                  "warning")
                : "failure"
            }
          />
          Calibration:{" "}
          {calibration
            ? (calibration.state ?? "no reading persisted")
            : "unavailable"}
        </span>
        <span className="text-text-secondary">
          Evaluation completion:{" "}
          {evaluationCompletionPct !== null ? (
            <span className="tabular-metric text-text-primary">
              {evaluationCompletionPct}%
            </span>
          ) : (
            "not available"
          )}{" "}
          <span className="text-xs">
            (share of real traces the flash judge has evaluated, not a quality
            score)
          </span>
        </span>
      </section>

      <section aria-label="Live metrics" className="mt-6">
        <LiveMetricTiles showConnectionRow />
      </section>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AttentionRequired
          calibration={calibration}
          disagreementTraces={overview?.disagreementTraces ?? []}
          blockedTotal={overview?.blockedTotal ?? 0}
          blockedByReason={overview?.blockedByReason ?? []}
        />
        {overview ? (
          <JudgeStateDistribution counts={overview.judgeStateCounts} />
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
      </div>

      <div className="mt-6">
        {overview ? (
          <ReliabilityPipeline
            blockedByReason={overview.blockedByReason}
            flashEvaluatedCount={evaluatedCount ?? 0}
            flashNeverRanCount={overview.judgeStateCounts.never_evaluated}
            frontierSampledCount={overview.frontierSampledCount}
          />
        ) : null}
      </div>

      <div className="mt-6">
        <RecentTraces
          title="Recent investigations"
          description="Frontier/flash disagreements and blocked requests surfaced first, over routine traffic."
          traces={overview?.recentInvestigations ?? []}
        />
      </div>
    </div>
  );
}
