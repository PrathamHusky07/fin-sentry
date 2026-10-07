"use client";

import Link from "next/link";
import { ActivityChart } from "@/components/activity-chart";
import { CalibrationInstrument } from "@/components/calibration-instrument";
import { ConnectionStrip } from "@/components/connection-strip";
import { EvalTelemetry } from "@/components/eval-telemetry";
import { InView } from "@/components/in-view";
import { PageHeader } from "@/components/page-header";
import { formatUtc, relativeTime } from "@/lib/format";
import type { CalibrationHealthResponse, TraceListItem } from "@/lib/trace-api";
import { useMetricsSnapshot } from "@/lib/use-metrics-snapshot";
import { useNow } from "@/lib/use-now";

// Readouts only render after the first snapshot arrives in the browser, so
// the viewer’s own locale is safe to use (no server-rendered text to match).
const NUMBER = new Intl.NumberFormat(undefined);

function fmt(n: number | null | undefined): string | null {
  return n === null || n === undefined ? null : NUMBER.format(n);
}

/**
 * Telemetry: what the system is doing right now, as a console. The SSE
 * connection feeds the freshness rail, the request readouts, the evaluation
 * telemetry and the activity chart. The calibration reading is persisted
 * data passed in from the server. The newest persisted execution is the one
 * fact folded in from the cut "recent events" list: it says how old the
 * last real request is, which the metrics bucket alone does not.
 */
export function LiveOperations({
  calibration,
  newest,
}: {
  calibration: CalibrationHealthResponse | null;
  /** The most recent persisted execution, or null when none or unavailable. */
  newest: TraceListItem | null;
}) {
  const now = useNow();
  const { snapshot, receivedAt, connectionState, throughputHistory } =
    useMetricsSnapshot();
  const bucket = snapshot?.throughput ?? null;
  const live = connectionState === "open" && bucket !== null && !bucket.stale;

  const readouts = [
    {
      label: "Throughput",
      value: fmt(bucket?.total_requests),
      unit: "requests",
      scope: "Gateway requests in the latest one-minute bucket",
    },
    {
      label: "Average latency",
      value: fmt(bucket?.avg_latency_ms),
      unit: "ms",
      scope: "Mean request latency in the same bucket",
    },
    {
      label: "p95 latency",
      value: fmt(bucket?.p95_latency_ms),
      unit: "ms",
      scope: "Approximate 95th percentile in the same bucket",
    },
  ];

  return (
    <div className="ctx ctx-live flex-1">
      <div className="mx-auto w-full max-w-7xl px-4 pt-12 pb-8 sm:px-8 sm:pt-16">
        <PageHeader eyebrow="Telemetry" title="Live Operations">
          What the system is doing right now. Every readout names what it
          measures and how fresh it is.
        </PageHeader>
      </div>

      <ConnectionStrip
        connectionState={connectionState}
        snapshot={snapshot}
        receivedAt={receivedAt}
        now={now}
      />

      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8">
        <section
          aria-labelledby="activity-heading"
          className="border-line-hover bg-background-elevated/80 relative overflow-hidden rounded-2xl border"
        >
          <span
            aria-hidden="true"
            className="via-signal/50 absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent to-transparent"
          />
          <h2 id="activity-heading" className="sr-only">
            Request activity
          </h2>
          <dl className="divide-border grid grid-cols-1 divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {readouts.map((readout) => (
              <div key={readout.label} className="px-6 py-7">
                <dt className="text-text-secondary text-sm">{readout.label}</dt>
                <dd
                  className={`tabular-metric mt-2 text-6xl font-semibold tracking-tighter ${bucket?.stale ? "text-text-secondary" : "text-text-primary"}`}
                >
                  {readout.value ?? "no data"}
                  {readout.value ? (
                    <span className="text-text-tertiary ml-2 text-base font-normal tracking-normal">
                      {readout.unit}
                    </span>
                  ) : null}
                </dd>
                <dd className="text-text-tertiary mt-2 text-sm leading-snug">
                  {readout.scope}
                </dd>
              </div>
            ))}
          </dl>
          <p className="border-border text-text-tertiary border-t px-6 py-3 text-sm">
            {bucket?.window_end
              ? `${bucket.stale ? "Stale. " : ""}Latest one-minute bucket ended ${formatUtc(bucket.window_end)}.`
              : snapshot
                ? "No bucket reported."
                : "Waiting for the first snapshot."}
            {newest ? (
              <>
                {" "}
                Newest persisted execution {formatUtc(newest.timestamp_utc)}
                {now !== null
                  ? `, ${relativeTime(newest.timestamp_utc, now)}`
                  : ""}
                .{" "}
                <Link
                  href={`/investigations?trace=${newest.app_trace_id}`}
                  className="text-accent hover:text-text-primary underline underline-offset-4"
                >
                  Open it
                </Link>
              </>
            ) : null}
          </p>
        </section>

        <div className="mt-16">
          <EvalTelemetry snapshot={snapshot} />
        </div>

        <section
          aria-labelledby="chart-heading"
          className="border-border mt-16 border-t pt-16"
        >
          <h2
            id="chart-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            Request activity as it arrives
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-2xl text-base leading-relaxed">
            Buckets that arrived over the stream while this page has been open.
          </p>
          <ActivityChart history={throughputHistory} live={live} />
        </section>

        <InView className="border-border mt-16 border-t pt-16">
          <CalibrationInstrument health={calibration} />
        </InView>
      </div>
    </div>
  );
}
