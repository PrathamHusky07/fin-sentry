"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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
    <div className="border-border-strong bg-surface-high rounded-md border px-3 py-2 text-xs">
      <p className="text-text-tertiary font-mono">
        Bucket ending {clock(label)} UTC
      </p>
      {payload.map((p) => (
        <p key={p.name} className="text-text-primary tabular-metric mt-1">
          {p.name}: {p.value ?? "no data"}
          {p.value != null ? ` ${unit}` : ""}
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
}: {
  history: ThroughputHistoryPoint[];
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
      <div className="grid gap-x-10 gap-y-8 lg:grid-cols-2">
        <figure>
          <figcaption className="eyebrow">Requests per bucket</figcaption>
          <div
            className="mt-3 h-48"
            role="img"
            aria-label={`Requests per one-minute bucket. ${history.length} ${history.length === 1 ? "bucket" : "buckets"} received.`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={points}
                margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
              >
                {grid}
                {xAxis}
                <YAxis
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  width={32}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: "var(--surface)" }}
                  content={<ChartTooltip unit="requests" />}
                />
                <Bar
                  dataKey="requests"
                  name="requests"
                  fill="var(--accent)"
                  maxBarSize={28}
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={!reducedMotion}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </figure>

        <figure>
          <figcaption className="eyebrow">
            Latency, milliseconds (solid average, dashed p95)
          </figcaption>
          <div
            className="mt-3 h-48"
            role="img"
            aria-label={`Average and p95 latency per one-minute bucket. ${history.length} ${history.length === 1 ? "bucket" : "buckets"} received.`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={points}
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
                <Tooltip content={<ChartTooltip unit="ms" />} />
                <Line
                  type="linear"
                  dataKey="avg"
                  name="average"
                  stroke="var(--signal)"
                  strokeWidth={2}
                  dot={{ r: 4.5, fill: "var(--signal)", strokeWidth: 0 }}
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
    </div>
  );
}
