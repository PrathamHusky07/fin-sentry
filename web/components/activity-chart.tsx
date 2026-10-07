"use client";

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
import type { ThroughputHistoryPoint } from "@/lib/use-metrics-snapshot";
import { usePrefersReducedMotion } from "@/lib/use-prefers-reduced-motion";

const BUCKET_MS = 60_000;
/** A gap wider than this between two buckets means minutes with no data.
 * The line breaks there instead of drawing across them. */
const GAP_MS = 90_000;

interface ChartPoint {
  t: number;
  requests: number | null;
  avg: number | null;
  p95: number | null;
}

function clock(t: number): string {
  const d = new Date(t);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** One point per real bucket, with a null point inserted wherever buckets
 * are more than GAP_MS apart so the line breaks instead of interpolating. */
function toPoints(history: ThroughputHistoryPoint[]): ChartPoint[] {
  const points: ChartPoint[] = [];
  history.forEach((h, i) => {
    const t = new Date(h.windowEnd).getTime();
    const previous = i > 0 ? new Date(history[i - 1].windowEnd).getTime() : t;
    if (i > 0 && t - previous > GAP_MS) {
      points.push({
        t: previous + BUCKET_MS,
        requests: null,
        avg: null,
        p95: null,
      });
    }
    points.push({
      t,
      requests: h.totalRequests,
      avg: h.avgLatencyMs,
      p95: h.p95LatencyMs,
    });
  });
  return points;
}

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | null }[];
  label?: number;
  unit: string;
}) {
  if (!active || !payload?.length || label === undefined) return null;
  return (
    <div className="floating rounded-lg px-4 py-3 text-sm">
      <p className="text-text-tertiary font-mono text-xs">
        Bucket ending {clock(label)} UTC
      </p>
      {payload.map((p) => (
        <p
          key={p.name}
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

/**
 * Requests and latency per one-minute bucket, built only from buckets that
 * arrived over the real SSE connection while this page was open. It never
 * backfills, never smooths, and never draws across missing minutes. With
 * fewer than two buckets it shows the empty axes and the one real point
 * rather than a manufactured line.
 */
export function ActivityChart({
  history,
  live,
}: {
  history: ThroughputHistoryPoint[];
  /** True only while the stream is open and the newest bucket is fresh. */
  live: boolean;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const points = toPoints(history);
  const times = points.map((p) => p.t);
  const domain: [number, number] =
    times.length >= 2
      ? [Math.min(...times) - BUCKET_MS / 2, Math.max(...times) + BUCKET_MS / 2]
      : times.length === 1
        ? [times[0] - 5 * BUCKET_MS, times[0] + 5 * BUCKET_MS]
        : [0, 1];

  const sparse = history.length < 2;
  const newest = history.length > 0 ? history[history.length - 1] : null;
  const newestT = newest ? new Date(newest.windowEnd).getTime() : null;
  const edge =
    live && newestT !== null ? (
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
        <figure>
          <figcaption className="text-text-secondary flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
            <span>Requests per bucket</span>
            {live && newest ? (
              <span className="text-signal flex items-center gap-2">
                <StatusDot color="signal" live />
                Live edge: newest bucket ended {clock(newestT ?? 0)} UTC
              </span>
            ) : null}
          </figcaption>
          <div
            className="mt-2 h-44"
            role="img"
            aria-label={`Requests per one-minute bucket. ${history.length} ${history.length === 1 ? "bucket" : "buckets"} received.`}
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
                  fill="var(--accent)"
                  maxBarSize={24}
                  radius={[4, 4, 0, 0]}
                  activeBar={{ fill: "var(--text-primary)" }}
                  isAnimationActive={!reducedMotion}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </figure>

        <figure className="mt-4">
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
            aria-label={`Average and p95 latency per one-minute bucket. ${history.length} ${history.length === 1 ? "bucket" : "buckets"} received.`}
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
        {history.length === 0
          ? "No bucket has arrived yet. The first snapshot fills this in."
          : sparse
            ? "One bucket has arrived since this page opened, so it is drawn as a single point. A line needs a second bucket, and the metrics view advances once a minute."
            : `${history.length} buckets have arrived since this page opened. Missing minutes stay empty and the line breaks across them.`}{" "}
        There is no stored history behind this chart.
      </p>

      {history.length > 0 ? (
        <details className="mt-3">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline underline-offset-4">
            View the buckets as a table
          </summary>
          <table className="mt-2 w-full max-w-xl text-left text-sm">
            <caption className="sr-only">
              One-minute buckets received over the stream
            </caption>
            <thead>
              <tr className="text-text-tertiary">
                <th className="py-2 font-normal">Bucket ended (UTC)</th>
                <th className="py-2 text-right font-normal">Requests</th>
                <th className="py-2 text-right font-normal">Avg ms</th>
                <th className="py-2 text-right font-normal">p95 ms</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.windowEnd} className="border-border border-t">
                  <td className="tabular-metric text-text-secondary py-2">
                    {clock(new Date(h.windowEnd).getTime())}
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
