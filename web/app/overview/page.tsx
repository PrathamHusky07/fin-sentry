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

  // Completion (did the judge finish running) and quality are different
  // questions -- see docs/internal/day9-frontend-data-contract.md's "No
  // quality %" note. "Complete" and "partial" are also never collapsed
  // into one number below: a partial evaluation (some of the three RAGAS
  // metrics skipped) is not the same claim as a complete one, even though
  // both count toward "evaluation completion."
  const completedOrPartialCount = overview
    ? overview.judgeStateCounts.evaluated +
      overview.judgeStateCounts.partially_evaluated
    : null;
  const evaluationCompletionPct =
    overview && overview.totalRequests > 0 && completedOrPartialCount !== null
      ? ((completedOrPartialCount / overview.totalRequests) * 100).toFixed(1)
      : null;

  const calibrationColor = calibration
    ? (CALIBRATION_STATE_COLOR[calibration.state ?? ""] ?? "warning")
    : "failure";

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-text-primary text-3xl font-semibold tracking-tight">
          Overview
        </h1>
        <p className="text-text-secondary text-sm">
          Is the platform healthy, what needs attention, and why.
        </p>
      </div>

      <section
        aria-label="System status"
        className="border-border bg-background-elevated mt-6 flex flex-col gap-4 rounded-md border p-5 sm:flex-row sm:items-center sm:gap-8"
      >
        <div className="flex items-center gap-3">
          <StatusDot color={calibrationColor} />
          <div>
            <p className="text-text-secondary text-xs tracking-wide uppercase">
              Calibration
            </p>
            <p className="text-text-primary text-xl font-semibold">
              {calibration
                ? (calibration.state ?? "no reading persisted")
                : "unavailable"}
            </p>
          </div>
        </div>
        <div className="bg-border hidden h-10 w-px sm:block" />
        <div>
          <p className="text-text-secondary text-xs tracking-wide uppercase">
            Evaluation completion
          </p>
          <p className="tabular-metric text-text-primary text-xl font-semibold">
            {evaluationCompletionPct !== null
              ? `${evaluationCompletionPct}%`
              : "not available"}
          </p>
          <p className="text-text-secondary mt-0.5 text-xs">
            Share of real traces the flash judge has evaluated -- not a quality
            score.
          </p>
        </div>
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
            flashCompleteCount={overview.judgeStateCounts.evaluated}
            flashPartialCount={overview.judgeStateCounts.partially_evaluated}
            flashNeverRanCount={overview.judgeStateCounts.never_evaluated}
            frontierSampledCount={overview.frontierSampledCount}
          />
        ) : null}
      </div>

      <div className="mt-6">
        <RecentTraces
          title="Recent investigations"
          description="Frontier/flash disagreements and blocked requests surfaced first, over routine traffic. Repeated questions are grouped; every real execution is still visible in Investigations."
          groups={overview?.recentInvestigations ?? []}
        />
      </div>
    </div>
  );
}
