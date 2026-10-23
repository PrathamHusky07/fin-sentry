import type { Metadata } from "next";
import Link from "next/link";
import { AttentionList } from "@/components/attention-list";
import { CoverageLedger } from "@/components/coverage-ledger";
import { FeaturedDisagreement } from "@/components/featured-disagreement";
import { InView } from "@/components/in-view";
import { PageHeader } from "@/components/page-header";
import { RequestFlow } from "@/components/request-flow";
import { SystemState } from "@/components/system-state";
import { buildAttentionItems } from "@/lib/attention";
import {
  fetchCalibrationHealth,
  fetchOverviewData,
  fetchTraceDetail,
} from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Overview | Fin-Sentry",
};

// Read on every request. Relative phrases such as "the newest 21h ago" are measured from now,
// and a page rendered once at build time would freeze them.
export const dynamic = "force-dynamic";

/**
 * The command center. It answers one question: what needs attention right
 * now. The order is the argument: the system state, the one case the second
 * judge exists for, the ranked signals, how far evaluation reached and how
 * requests ended. There is deliberately no live telemetry here (that is
 * Live Operations) and no per-execution list (that is Investigations).
 * Every figure is derived from the persisted trace list and the persisted
 * calibration reading.
 */
export default async function OverviewPage() {
  const [overview, calibration] = await Promise.all([
    fetchOverviewData(),
    fetchCalibrationHealth(),
  ]);

  // Quote the real scores on disagreement items. Three at most, matching
  // the number of disagreement items the attention list will show.
  const disagreementDetails = overview
    ? await Promise.all(
        overview.disagreementTraces
          .slice(0, 3)
          .map((trace) => fetchTraceDetail(trace.app_trace_id)),
      )
    : [];

  const items = buildAttentionItems({
    overview,
    calibration,
    disagreementDetails,
  });

  const signals = items.filter((item) => item.tone !== "disagreement");
  const featured = overview?.disagreementTraces[0] ?? null;

  return (
    <div className="ctx ctx-overview flex-1">
      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
        <PageHeader
          eyebrow="Command center"
          title="Overview"
          aside={
            <Link
              href="/operations"
              className="border-line-active text-text-primary hover:bg-surface-hover inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium transition-colors"
            >
              Live telemetry is on Live Operations
              <span aria-hidden="true">→</span>
            </Link>
          }
        >
          Is something wrong right now, and what should be investigated first.
        </PageHeader>

        <div className="mt-14">
          <SystemState
            overview={overview}
            calibration={calibration}
            items={items}
          />
        </div>

        {overview ? (
          <div className="mt-16 flex flex-col gap-16">
            {featured ? (
              <FeaturedDisagreement
                trace={featured}
                detail={disagreementDetails[0] ?? null}
                others={overview.disagreementTraces.length - 1}
                othersIsFloor={overview.disagreementIsWindow}
              />
            ) : null}
            <AttentionList items={signals} />
            <InView className="border-border border-t pt-16">
              <CoverageLedger counts={overview.judgeStateCounts} />
            </InView>
            <InView className="border-border border-t pt-16">
              <RequestFlow
                flow={overview.flow}
                frontierCount={overview.frontierSampledCount}
              />
            </InView>
          </div>
        ) : (
          <div className="mt-16 space-y-8">
            {signals.length > 0 ? <AttentionList items={signals} /> : null}
            <p className="border-failure/40 bg-failure/5 text-text-primary rounded-lg border p-5 text-base">
              The gateway did not return the trace list, so coverage and the
              request funnel are not shown. Check that the gateway is running,
              then reload.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
