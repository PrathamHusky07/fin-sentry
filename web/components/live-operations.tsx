"use client";

import Link from "next/link";
import { CalibrationInstrument } from "@/components/calibration-instrument";
import { CapabilityStrip } from "@/components/capability-strip";
import { EvalTelemetry } from "@/components/eval-telemetry";
import { GatewayProbeReadout } from "@/components/gateway-probe-readout";
import { InView } from "@/components/in-view";
import { PageHeader } from "@/components/page-header";
import { formatUtc, relativeTime } from "@/lib/format";
import type { GatewayHealthCheck } from "@/lib/gateway-health";
import type { GatewayProbeSummary } from "@/lib/gateway-probe";
import type { CalibrationHealthResponse, TraceListItem } from "@/lib/trace-api";
import { useMetricsSnapshot } from "@/lib/use-metrics-snapshot";
import { useNow } from "@/lib/use-now";

/**
 * Telemetry on what the evaluation layer is doing. The judges' latest verdicts arrive over the
 * SSE snapshot relay, the calibration reading is persisted data passed in from the server, and
 * the gateway health-route round trip closes the page as a supporting instrument. The RAG
 * request latency is not on this page: the answering model is a deliberate basic baseline, and
 * the platform being shown is the evaluation of it. The newest persisted execution is the one
 * fact kept from the old activity section, because it says how old the data behind a stale
 * card is.
 */
export function LiveOperations({
  calibration,
  newest,
  health,
  probe,
}: {
  calibration: CalibrationHealthResponse | null;
  /** The most recent persisted execution, or null when none or unavailable. */
  newest: TraceListItem | null;
  /** The gateway health route timed by the web server, or null when it was not reachable. */
  health: GatewayHealthCheck | null;
  /** The newest stored gateway round-trip probe, or null when its store did not answer. */
  probe: GatewayProbeSummary | null;
}) {
  const now = useNow();
  const { snapshot, connectionState } = useMetricsSnapshot();

  return (
    <div className="ctx ctx-live flex-1">
      <div className="mx-auto w-full max-w-7xl px-4 pt-12 pb-10 sm:px-8 sm:pt-16">
        <PageHeader eyebrow="Telemetry" title="Live Operations">
          What the evaluation layer scored most recently, how far the frontier
          judge can be trusted, and one reading of the gateway. Every readout
          names what it measures and how fresh it is.
        </PageHeader>
        {newest ? (
          <p className="text-text-tertiary mt-6 max-w-2xl text-base leading-snug sm:text-sm">
            Newest recorded request {formatUtc(newest.timestamp_utc)}
            {now !== null ? `, ${relativeTime(newest.timestamp_utc, now)}` : ""}
            .{" "}
            <Link
              href={`/investigations?trace=${newest.app_trace_id}`}
              className="text-accent hover:text-text-primary inline-flex min-h-11 items-center underline underline-offset-4 sm:min-h-6"
            >
              Open it
            </Link>
          </p>
        ) : null}
      </div>

      <CapabilityStrip />

      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
        <InView>
          <EvalTelemetry snapshot={snapshot} connection={connectionState} />
        </InView>

        <InView className="border-border mt-16 border-t pt-16">
          <CalibrationInstrument health={calibration} />
        </InView>

        <InView className="border-border mt-16 border-t pt-16">
          <GatewayProbeReadout probe={probe} health={health} now={now} />
        </InView>
      </div>
    </div>
  );
}
