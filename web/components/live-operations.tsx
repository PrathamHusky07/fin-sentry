"use client";

import Link from "next/link";
import { useMemo, type CSSProperties } from "react";
import { ActivityChart } from "@/components/activity-chart";
import { CalibrationInstrument } from "@/components/calibration-instrument";
import { ConnectionStrip } from "@/components/connection-strip";
import { EvalTelemetry } from "@/components/eval-telemetry";
import { GatewayProbeReadout } from "@/components/gateway-probe-readout";
import { InView } from "@/components/in-view";
import { PageHeader } from "@/components/page-header";
import { PersistedThroughput } from "@/components/persisted-throughput";
import { formatUtc, relativeTime } from "@/lib/format";
import type { GatewayHealthCheck } from "@/lib/gateway-health";
import type { GatewayProbeSummary } from "@/lib/gateway-probe";
import type { ThroughputHistory } from "@/lib/metrics-snapshot";
import { activityScope, mergeActivityBuckets } from "@/lib/throughput-history";
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
 * telemetry and the activity chart. The stored throughput history and the
 * calibration reading are persisted data passed in from the server. The newest persisted execution is the one
 * fact folded in from the cut "recent events" list: it says how old the
 * last real request is, which the metrics bucket alone does not.
 */
export function LiveOperations({
  calibration,
  newest,
  history,
  health,
  probe,
}: {
  calibration: CalibrationHealthResponse | null;
  /** The stored one-minute buckets, or null when the gateway did not return them. */
  history: ThroughputHistory | null;
  /** The most recent persisted execution, or null when none or unavailable. */
  newest: TraceListItem | null;
  /** The gateway health route timed by the web server, or null when it was not reachable. */
  health: GatewayHealthCheck | null;
  /** The newest stored gateway round-trip probe, or null when its store did not answer. */
  probe: GatewayProbeSummary | null;
}) {
  const now = useNow();
  const { snapshot, receivedAt, connectionState, throughputHistory } =
    useMetricsSnapshot();
  const bucket = snapshot?.throughput ?? null;
  const live = connectionState === "open" && bucket !== null && !bucket.stale;

  // Stored buckets seed the chart and the received ones merge into the same
  // series on window end. With no stored history this is the received buckets
  // alone, exactly as the chart behaved before.
  const activity = useMemo(
    () => mergeActivityBuckets(history?.buckets ?? [], throughputHistory, live),
    [history, throughputHistory, live],
  );

  // Judged against the clock, so a quiet system shows the last activity that was recorded,
  // with its real time, and is never described as the last hour.
  const scope = activityScope(activity, now);

  // Each readout points at the chart that draws it. Average and p95 share the
  // latency chart, so those two links land on the same figure.
  const readouts = [
    {
      label: "Throughput",
      value: fmt(bucket?.total_requests),
      unit: "requests",
      scope: "RAG queries recorded in the latest one-minute bucket",
      target: "#activity-requests",
      chart: "requests per bucket",
    },
    {
      label: "Average RAG latency",
      value: fmt(bucket?.avg_latency_ms),
      unit: "ms",
      scope:
        "End-to-end RAG (local model). Mean latency of those queries, retrieval and generation included",
      target: "#activity-latency",
      chart: "latency per bucket",
    },
    {
      label: "p95 RAG latency",
      value: fmt(bucket?.p95_latency_ms),
      unit: "ms",
      scope:
        "End-to-end RAG (local model). 95th percentile of those queries, from the same requests as the average",
      target: "#activity-latency",
      chart: "latency per bucket",
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
          <GatewayProbeReadout probe={probe} now={now} />
          <h2 id="activity-heading" className="sr-only">
            Request activity
          </h2>
          <dl className="divide-border grid grid-cols-1 divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {readouts.map((readout) => (
              <div
                key={readout.label}
                className="row-reveal reveal-host group px-6 py-7"
                style={
                  {
                    "--tone": bucket?.stale
                      ? "var(--warning)"
                      : "var(--signal)",
                  } as CSSProperties
                }
              >
                <dt className="text-text-secondary group-hover:text-text-primary text-sm transition-colors duration-[var(--dur-base)]">
                  {/* The label is the link, and its overlay makes the whole
                      cell the target. The dt is not transformed, so the
                      overlay reaches the cell edges. */}
                  <a
                    href={readout.target}
                    className="rounded-sm after:absolute after:inset-0 after:rounded-lg"
                  >
                    <span>{readout.label}</span>
                    <span className="sr-only">
                      , see {readout.chart} in the chart below
                    </span>
                  </a>
                </dt>
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
                <dd className="text-text-tertiary group-hover:text-text-secondary mt-2 text-sm leading-snug transition-colors duration-[var(--dur-base)]">
                  {readout.scope}
                </dd>
                <dd className="reveal-on-hover mt-3 text-sm leading-snug">
                  {bucket?.window_start && bucket.window_end ? (
                    <span className="text-text-tertiary block">
                      Bucket {formatUtc(bucket.window_start)} to{" "}
                      {formatUtc(bucket.window_end)}
                      {bucket.stale ? ", stale" : ""}
                    </span>
                  ) : null}
                  <span className="text-accent nudge inline-flex min-h-6 items-center gap-1.5 font-medium">
                    See {readout.chart}
                    <span aria-hidden="true">↓</span>
                  </span>
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
          <div
            data-gateway-health={health ? "measured" : "not-measured"}
            className="border-border flex flex-col gap-1 border-t px-6 py-4 sm:flex-row sm:items-baseline sm:gap-6"
          >
            <p className="text-text-secondary shrink-0 text-sm">
              Checked just now by this page
              <span className="tabular-metric text-text-primary ml-3 text-lg font-semibold">
                {health ? `${health.medianMs} ms` : "not measured"}
              </span>
            </p>
            <p className="text-text-tertiary text-sm leading-snug">
              {health
                ? `Median of ${health.samples} requests to the gateway health route, timed by the web server at ${formatUtc(health.measuredAt)} and not stored. It runs no retrieval and no model, so it is the cost of reaching the gateway and not request latency.`
                : "The gateway health route did not answer within its time budget, so no round trip was timed. Nothing is shown in its place."}
            </p>
          </div>
        </section>

        <InView className="mt-16">
          <EvalTelemetry snapshot={snapshot} />
        </InView>

        <section
          aria-labelledby="chart-heading"
          className="border-border mt-16 border-t pt-16"
        >
          <h2
            id="chart-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            {scope.kind === "last-recorded"
              ? "Last recorded activity"
              : scope.kind === "current"
                ? "Request buckets, last hour"
                : "Request buckets"}
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-2xl text-base leading-relaxed">
            {scope.kind === "last-recorded"
              ? `Nothing has been recorded since ${formatUtc(scope.endedAt)}, so this chart shows the last hour of activity that was stored before then. Each bucket is dated.`
              : "One-minute buckets read from the metrics view. The newest turns live while the stream is open and that bucket is fresh."}
          </p>
          <ActivityChart buckets={activity} scope={scope} />
        </section>

        <section
          aria-labelledby="history-heading"
          className="border-border mt-16 border-t pt-16"
        >
          <h2
            id="history-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            Stored request history
          </h2>
          <p className="text-text-secondary mt-2 mb-6 max-w-2xl text-base leading-relaxed">
            The latest one-minute buckets persisted by the metrics view. The
            live bucket above is the newest row of the same view. A bucket shows
            no p95 when the exact percentile view did not count the same
            requests, which is the case for buckets whose events had already
            expired from the stream when that view was added.
          </p>
          <PersistedThroughput history={history} />
        </section>

        <InView className="border-border mt-16 border-t pt-16">
          <CalibrationInstrument health={calibration} />
        </InView>
      </div>
    </div>
  );
}
