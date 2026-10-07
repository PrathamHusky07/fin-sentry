"use client";

import { useRouter } from "next/navigation";
import { ActivityChart } from "@/components/activity-chart";
import { CalibrationInstrument } from "@/components/calibration-instrument";
import { ConnectionStrip } from "@/components/connection-strip";
import { OpsTimeline } from "@/components/ops-timeline";
import { PageHeader } from "@/components/page-header";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";
import type { CalibrationHealthResponse, TraceListItem } from "@/lib/trace-api";
import { useMetricsSnapshot } from "@/lib/use-metrics-snapshot";
import { useNow } from "@/lib/use-now";
import { formatUtc } from "@/lib/format";

interface Readout {
  label: string;
  value: string | null;
  unit?: string;
  scope: string;
  stale: boolean | null;
  asOf: string | null;
}

// Readouts only render after the first snapshot arrives in the browser, so
// the viewer’s own locale is safe to use (no server-rendered text to match).
const NUMBER = new Intl.NumberFormat(undefined);

function fmt(n: number | null | undefined): string | null {
  return n === null || n === undefined ? null : NUMBER.format(n);
}

function buildReadouts(snapshot: MetricsSnapshot | null): Readout[] {
  const throughput = snapshot?.throughput ?? null;
  const tokens = snapshot?.tokens ?? null;
  const cost = snapshot?.cost ?? null;
  const tokenTotal =
    tokens &&
    tokens.input_tokens_total !== null &&
    tokens.output_tokens_total !== null
      ? tokens.input_tokens_total +
        tokens.output_tokens_total +
        (tokens.thoughts_tokens_total ?? 0)
      : null;

  return [
    {
      label: "Throughput",
      value: fmt(throughput?.total_requests),
      unit: "requests",
      scope: "Gateway requests in the latest one-minute bucket",
      stale: throughput?.stale ?? null,
      asOf: throughput?.window_end ?? null,
    },
    {
      label: "Average latency",
      value: fmt(throughput?.avg_latency_ms),
      unit: "ms",
      scope: "Mean request latency in the same bucket",
      stale: throughput?.stale ?? null,
      asOf: throughput?.window_end ?? null,
    },
    {
      label: "p95 latency",
      value: fmt(throughput?.p95_latency_ms),
      unit: "ms",
      scope: "Approximate 95th percentile in the same bucket",
      stale: throughput?.stale ?? null,
      asOf: throughput?.window_end ?? null,
    },
    {
      label: "Judge tokens",
      value: fmt(tokenTotal),
      unit: "tokens",
      scope: `Flash judge only: Gemini input, output and thinking tokens in its latest one-minute bucket${tokens?.gemini_calls_total != null ? `, ${tokens.gemini_calls_total} calls` : ""}`,
      stale: tokens?.stale ?? null,
      asOf: tokens?.window_end ?? null,
    },
    {
      label: "Judge cost",
      value:
        cost?.cost_total_usd != null
          ? `$${cost.cost_total_usd.toFixed(6)}`
          : null,
      scope:
        "Flash judge only, estimated at Vertex AI standard pricing, in its latest one-minute bucket. Not platform spend.",
      stale: cost?.stale ?? null,
      asOf: cost?.window_end ?? null,
    },
  ];
}

/**
 * Telemetry: what the system is doing right now. The SSE connection feeds
 * the freshness strip, the readouts and the activity chart. The calibration
 * reading and the recent-execution timeline are persisted data passed in
 * from the server, and the timeline has an explicit refresh instead of
 * pretending to stream.
 */
export function LiveOperations({
  calibration,
  recent,
}: {
  calibration: CalibrationHealthResponse | null;
  recent: TraceListItem[] | null;
}) {
  const router = useRouter();
  const now = useNow();
  const { snapshot, receivedAt, connectionState, throughputHistory } =
    useMetricsSnapshot();
  const readouts = buildReadouts(snapshot);

  const primary = readouts.slice(0, 3);
  const judge = readouts.slice(3);
  const bucket = snapshot?.throughput ?? null;

  return (
    <div>
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
          className="border-border-strong bg-background-elevated rounded-2xl border"
        >
          <h2 id="activity-heading" className="sr-only">
            Request activity
          </h2>
          <dl className="divide-border grid grid-cols-1 divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {primary.map((readout) => (
              <div key={readout.label} className="px-6 py-6">
                <dt className="text-text-secondary text-sm">{readout.label}</dt>
                <dd
                  className={`tabular-metric mt-2 text-5xl font-semibold tracking-tight ${readout.stale ? "text-text-secondary" : "text-text-primary"}`}
                >
                  {readout.value ?? "no data"}
                  {readout.value && readout.unit ? (
                    <span className="text-text-tertiary ml-2 text-sm font-normal">
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
          </p>
          <div className="border-border border-t px-4 py-6 sm:px-6">
            <p className="text-text-primary text-lg font-semibold tracking-tight">
              Request activity as it arrives
            </p>
            <p className="text-text-secondary mt-1 mb-5 max-w-2xl text-sm">
              Buckets that arrived over the stream while this page has been
              open.
            </p>
            <ActivityChart history={throughputHistory} />
          </div>
        </section>

        <dl className="text-text-secondary mt-6 grid gap-x-10 gap-y-3 text-sm sm:grid-cols-2">
          {judge.map((readout) => (
            <div key={readout.label}>
              <dt className="text-text-tertiary">{readout.label}</dt>
              <dd
                className={`tabular-metric text-xl font-medium ${readout.stale ? "text-text-secondary" : "text-text-primary"}`}
              >
                {readout.value ?? "no data"}
                {readout.value && readout.unit ? (
                  <span className="text-text-tertiary ml-1.5 text-sm font-normal">
                    {readout.unit}
                  </span>
                ) : null}
              </dd>
              <dd className="mt-1 max-w-md leading-snug">{readout.scope}</dd>
            </div>
          ))}
        </dl>

        <div className="border-border mt-16 border-t pt-16">
          <CalibrationInstrument health={calibration} />
        </div>

        <section
          aria-labelledby="timeline-heading"
          className="border-border mt-16 border-t pt-16"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2
                id="timeline-heading"
                className="text-text-primary text-2xl font-semibold tracking-tight"
              >
                Recent operational events
              </h2>
              <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
                The newest persisted executions as of the last page load. This
                list does not stream.
              </p>
            </div>
            <button
              type="button"
              onClick={() => router.refresh()}
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 items-center rounded-lg border px-4 text-sm font-medium transition-colors"
            >
              Refresh list
            </button>
          </div>
          <div className="mt-6">
            <OpsTimeline traces={recent} />
          </div>
        </section>
      </div>
    </div>
  );
}
