"use client";

import {
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

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface ChartPoint {
  label: string;
  totalRequests: number | null;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
}

function TooltipCard({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border-border bg-background-elevated rounded-md border px-2.5 py-1.5 text-xs shadow-sm">
      <p className="text-text-secondary">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="text-text-primary tabular-metric">
          {p.name}: {p.value ?? "—"}
        </p>
      ))}
    </div>
  );
}

/**
 * Real, live-accumulated throughput/latency, scoped to this browsing
 * session -- see lib/use-metrics-snapshot.ts and the data contract's
 * revised time-series section. Never a historical trend: it starts empty
 * on page load and fills in only with buckets that genuinely arrived over
 * the real SSE connection. One axis per chart (never throughput and
 * latency sharing a scale) -- avg/p95 latency share units so they share
 * one axis, distinguished by line style, not color alone.
 */
export function RecentActivityChart({
  history,
}: {
  history: ThroughputHistoryPoint[];
}) {
  const reducedMotion = usePrefersReducedMotion();

  if (history.length < 2) {
    return (
      <p className="text-text-secondary mt-4 text-xs">
        Recent activity chart: not enough live buckets have arrived yet this
        session to draw a line ({history.length} of 2 minimum). This is not a
        historical trend -- it only ever shows buckets that arrive while this
        page is open.
      </p>
    );
  }

  const points: ChartPoint[] = history.map((h) => ({
    label: formatClock(h.windowEnd),
    totalRequests: h.totalRequests,
    avgLatencyMs: h.avgLatencyMs,
    p95LatencyMs: h.p95LatencyMs,
  }));

  return (
    <div className="mt-4">
      <p className="text-text-secondary text-xs">
        Recent activity -- live since this page opened, not a historical trend.{" "}
        {history.length} real buckets.
      </p>
      <div className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-text-secondary text-xs tracking-wide uppercase">
            Requests per minute
          </h3>
          <div className="mt-1 h-40">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={points}
                margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--border)"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                  minTickGap={24}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                  allowDecimals={false}
                />
                <Tooltip content={<TooltipCard />} />
                <Line
                  type="monotone"
                  dataKey="totalRequests"
                  name="requests"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  isAnimationActive={!reducedMotion}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <h3 className="text-text-secondary text-xs tracking-wide uppercase">
            Latency (ms)
          </h3>
          <div className="mt-1 h-40">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={points}
                margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--border)"
                  vertical={false}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--border)" }}
                  minTickGap={24}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                  tickLine={false}
                  axisLine={false}
                  width={28}
                />
                <Tooltip content={<TooltipCard />} />
                <Line
                  type="monotone"
                  dataKey="avgLatencyMs"
                  name="avg"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  isAnimationActive={!reducedMotion}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  dataKey="p95LatencyMs"
                  name="p95"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  strokeDasharray="4 3"
                  dot={{ r: 2 }}
                  isAnimationActive={!reducedMotion}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-text-secondary mt-1 text-[11px]">
            Solid: average. Dashed: p95.
          </p>
        </div>
      </div>
    </div>
  );
}
