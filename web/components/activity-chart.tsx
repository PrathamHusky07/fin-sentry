"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { StatusDot } from "@/components/status-dot";
import type { ActivityBucket } from "@/lib/throughput-history";
import { usePrefersReducedMotion } from "@/lib/use-prefers-reduced-motion";

const BUCKET_MS = 60_000;
/** A gap wider than this between two buckets means minutes with no data.
 * The line breaks there instead of drawing across them. */
const GAP_MS = 90_000;

interface ChartPoint {
  t: number;
  /** Requests for a stored bucket. A live bucket carries its count in
   * `liveRequests`, so the two draw as separately colored bars in one slot. */
  requests: number | null;
  liveRequests: number | null;
  avg: number | null;
  p95: number | null;
  source: ActivityBucket["source"] | null;
}

function clock(t: number): string {
  const d = new Date(t);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** One point per real bucket, with a null point inserted wherever buckets
 * are more than GAP_MS apart so the line breaks instead of interpolating. */
function toPoints(buckets: ActivityBucket[]): ChartPoint[] {
  const points: ChartPoint[] = [];
  buckets.forEach((b, i) => {
    const t = new Date(b.windowEnd).getTime();
    const previous = i > 0 ? new Date(buckets[i - 1].windowEnd).getTime() : t;
    if (i > 0 && t - previous > GAP_MS) {
      points.push({
        t: previous + BUCKET_MS,
        requests: null,
        liveRequests: null,
        avg: null,
        p95: null,
        source: null,
      });
    }
    const isLive = b.source === "live";
    points.push({
      t,
      requests: isLive ? null : b.totalRequests,
      liveRequests: isLive ? b.totalRequests : null,
      avg: b.avgLatencyMs,
      p95: b.p95LatencyMs,
      source: b.source,
    });
  });
  return points;
}

const SOURCE_LABEL = {
  stored: "Stored bucket",
  live: "Live bucket",
} as const;

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: {
    name?: string;
    value?: number | null;
    payload?: ChartPoint;
  }[];
  label?: number;
  unit: string;
}) {
  if (!active || !payload?.length || label === undefined) return null;
  const source = payload[0].payload?.source ?? null;
  // A stacked pair of bars reports both; only the one that has a value is a
  // real reading for this bucket.
  const rows = payload.filter((p) => p.value != null || source === null);
  return (
    <div className="floating rounded-lg px-4 py-3 text-sm">
      <p className="text-text-tertiary font-mono text-xs">
        Bucket ending {clock(label)} UTC
      </p>
      {source ? (
        <p
          className={`mt-1 text-xs font-medium ${source === "live" ? "text-signal" : "text-accent"}`}
        >
          {SOURCE_LABEL[source]}
        </p>
      ) : null}
      {rows.map((p, i) => (
        <p
          key={`${p.name}-${i}`}
          className="text-text-primary tabular-metric mt-1.5 flex items-baseline justify-between gap-6"
        >
          <span className="text-text-secondary">{p.name}</span>
          <span>
            {p.value ?? "no data"}
            {p.value != null ? ` ${unit}` : ""}
          </span>
        </p>
      ))}
    </div>
  );
}

const AXIS_TICK = { fontSize: 12, fill: "var(--text-tertiary)" };

/** What the paragraph under the charts says, from the real series alone. */
function caption(buckets: ActivityBucket[]): string {
  if (buckets.length === 0) {
    return "No bucket is available yet. Stored history or the first snapshot fills this in.";
  }
  const hasLive = buckets.some((b) => b.source === "live");
  const count =
    buckets.length === 1
      ? "One bucket in the last hour, so the latency chart shows a single point. A line needs a second bucket, and the metrics view advances once a minute."
      : `${buckets.length} buckets in the last hour. Missing minutes stay empty and the line breaks across them.`;
  const bars = hasLive
    ? "Blue bars are stored buckets and the cyan bar is the live one."
    : "Every bar is a stored bucket. None is live right now.";
  return `${count} ${bars} The next section holds the full stored history.`;
}

/**
 * Requests and latency per one-minute bucket for the last hour. The series is
 * the stored buckets merged with the buckets received over the SSE stream,
 * keyed on window end so a bucket in both is drawn once (see
 * mergeActivityBuckets). It never smooths, never fills a missing minute and
 * never draws across one. Only the newest bucket can be live, and only while
 * the stream is open and that bucket is fresh; every other bar is stored and
 * says so. With a single bucket it says plainly what it is waiting for.
 */
export function ActivityChart({ buckets }: { buckets: ActivityBucket[] }) {
  const reducedMotion = usePrefersReducedMotion();
  const points = useMemo(() => toPoints(buckets), [buckets]);
  const times = points.map((p) => p.t);
  const domain: [number, number] =
    times.length >= 2
      ? [Math.min(...times) - BUCKET_MS / 2, Math.max(...times) + BUCKET_MS / 2]
      : times.length === 1
        ? [times[0] - 5 * BUCKET_MS, times[0] + 5 * BUCKET_MS]
        : [0, 1];

  const newest = buckets.length > 0 ? buckets[buckets.length - 1] : null;
  const newestT = newest ? new Date(newest.windowEnd).getTime() : null;
  const liveEdge = newest?.source === "live";
  const edge =
    liveEdge && newestT !== null ? (
      <ReferenceLine
        x={newestT}
        stroke="var(--signal)"
        strokeOpacity={0.5}
        strokeDasharray="2 4"
      />
    ) : null;
  const xAxis = (
    <XAxis
      dataKey="t"
      type="number"
      scale="time"
      domain={domain}
      tickFormatter={clock}
      tick={AXIS_TICK}
      tickLine={false}
      axisLine={{ stroke: "var(--border-strong)" }}
      minTickGap={32}
    />
  );
  const grid = (
    <CartesianGrid
      stroke="var(--border)"
      strokeDasharray="2 4"
      vertical={false}
    />
  );

  return (
    <div>
      <div className="grid gap-y-2">
        <figure id="activity-requests" className="target-ring">
          <figcaption className="text-text-secondary flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
            <span className="flex flex-wrap items-center gap-x-5 gap-y-1">
              <span>Requests per bucket</span>
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="bg-accent h-3 w-3 rounded-sm opacity-70"
                />
                Stored
              </span>
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="bg-signal h-3 w-3 rounded-sm"
                />
                Live
              </span>
            </span>
            {newest ? (
              liveEdge ? (
                <span className="text-signal flex items-center gap-2">
                  <StatusDot color="signal" live />
                  {buckets.length === 1
                    ? `Live, waiting for the next bucket. Newest ended ${clock(newestT ?? 0)} UTC`
                    : `Live edge: newest bucket ended ${clock(newestT ?? 0)} UTC`}
                </span>
              ) : (
                <span className="text-text-tertiary flex items-center gap-2">
                  <StatusDot color="neutral" />
                  Not live. Newest bucket ended {clock(newestT ?? 0)} UTC
                </span>
              )
            ) : null}
          </figcaption>
          <div
            className="mt-2 h-44"
            role="img"
            aria-label={`Requests per one-minute bucket, stored and live. ${buckets.length} ${buckets.length === 1 ? "bucket" : "buckets"} in the last hour.`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={points}
                syncId="ops-activity"
                margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
              >
                {grid}
                {xAxis}
                <YAxis
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: "rgb(255 255 255 / 0.05)" }}
                  content={<ChartTooltip unit="requests" />}
                  animationDuration={140}
                />
                {edge}
                <Bar
                  dataKey="requests"
                  name="requests"
                  stackId="requests"
                  fill="var(--accent)"
                  fillOpacity={0.7}
                  maxBarSize={24}
                  radius={[4, 4, 0, 0]}
                  activeBar={{ fill: "var(--text-primary)", fillOpacity: 1 }}
                  isAnimationActive={!reducedMotion}
                />
                <Bar
                  dataKey="liveRequests"
                  name="requests"
                  stackId="requests"
                  fill="var(--signal)"
                  maxBarSize={24}
                  radius={[4, 4, 0, 0]}
                  activeBar={{ fill: "var(--text-primary)" }}
                  isAnimationActive={!reducedMotion}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </figure>

        <figure id="activity-latency" className="target-ring mt-4">
          <figcaption className="text-text-secondary flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
            <span>Latency per bucket, milliseconds</span>
            <span className="flex items-center gap-2">
              <svg width="26" height="10" aria-hidden="true">
                <path d="M0 5H26" stroke="var(--signal)" strokeWidth="2" />
                <circle cx="13" cy="5" r="4" fill="var(--signal)" />
              </svg>
              Average
            </span>
            <span className="flex items-center gap-2">
              <svg width="26" height="10" aria-hidden="true">
                <path
                  d="M0 5H26"
                  stroke="var(--signal)"
                  strokeWidth="2"
                  strokeDasharray="5 4"
                />
                <circle
                  cx="13"
                  cy="5"
                  r="3.5"
                  fill="var(--background)"
                  stroke="var(--signal)"
                  strokeWidth="2"
                />
              </svg>
              p95
            </span>
          </figcaption>
          <div
            className="mt-2 h-52"
            role="img"
            aria-label={`Average and p95 latency per one-minute bucket. ${buckets.length} ${buckets.length === 1 ? "bucket" : "buckets"} in the last hour.`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={points}
                syncId="ops-activity"
                margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
              >
                {grid}
                {xAxis}
                <YAxis
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                />
                <Tooltip
                  cursor={{
                    stroke: "var(--text-secondary)",
                    strokeWidth: 1,
                    strokeDasharray: "3 3",
                  }}
                  content={<ChartTooltip unit="ms" />}
                  animationDuration={140}
                />
                {edge}
                <Line
                  type="linear"
                  dataKey="avg"
                  name="average"
                  stroke="var(--signal)"
                  strokeWidth={2}
                  dot={{ r: 4.5, fill: "var(--signal)", strokeWidth: 0 }}
                  activeDot={{
                    r: 7,
                    fill: "var(--signal)",
                    stroke: "var(--background)",
                    strokeWidth: 2,
                  }}
                  isAnimationActive={!reducedMotion}
                  connectNulls={false}
                />
                <Line
                  type="linear"
                  dataKey="p95"
                  name="p95"
                  stroke="var(--signal)"
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={{
                    r: 4.5,
                    fill: "var(--background)",
                    stroke: "var(--signal)",
                    strokeWidth: 2,
                  }}
                  activeDot={{
                    r: 7,
                    fill: "var(--background)",
                    stroke: "var(--signal)",
                    strokeWidth: 3,
                  }}
                  isAnimationActive={!reducedMotion}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </figure>
      </div>

      <p className="text-text-secondary mt-5 max-w-3xl text-base leading-relaxed">
        {caption(buckets)}
      </p>

      {buckets.length > 0 ? (
        <details className="mt-3">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline underline-offset-4">
            View the buckets as a table
          </summary>
          <table className="mt-2 w-full max-w-xl text-left text-sm">
            <caption className="sr-only">
              One-minute buckets in the last hour, stored and live
            </caption>
            <thead>
              <tr className="text-text-tertiary">
                <th className="py-2 font-normal">Bucket ended (UTC)</th>
                <th className="py-2 font-normal">Source</th>
                <th className="py-2 text-right font-normal">Requests</th>
                <th className="py-2 text-right font-normal">Avg ms</th>
                <th className="py-2 text-right font-normal">p95 ms</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((h) => (
                <tr key={h.windowEnd} className="border-border border-t">
                  <td className="tabular-metric text-text-secondary py-2">
                    {clock(new Date(h.windowEnd).getTime())}
                  </td>
                  <td className="text-text-secondary py-2">
                    {SOURCE_LABEL[h.source]}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {h.totalRequests ?? "no data"}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {h.avgLatencyMs ?? "no data"}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {h.p95LatencyMs ?? "no data"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </div>
  );
}
