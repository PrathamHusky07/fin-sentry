"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  historyRequestTotal,
  historyRows,
  type HistoryRow,
} from "@/lib/throughput-history";
import { formatUtc, relativeTime } from "@/lib/format";
import type { ThroughputHistory } from "@/lib/metrics-snapshot";
import { useNow } from "@/lib/use-now";
import { usePrefersReducedMotion } from "@/lib/use-prefers-reduced-motion";

const AXIS_TICK = { fontSize: 12, fill: "var(--text-tertiary)" };

const SERIES = [
  { key: "success", name: "success", color: "var(--positive)" },
  { key: "blocked", name: "blocked", color: "var(--warning)" },
  { key: "error", name: "error", color: "var(--failure)" },
] as const;

function HistoryTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: HistoryRow }[];
}) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;
  return (
    <div className="floating rounded-lg px-4 py-3 text-sm">
      <p className="text-text-tertiary font-mono text-xs">{row.span}</p>
      <p className="text-text-primary tabular-metric mt-1.5 flex justify-between gap-6">
        <span className="text-text-secondary">requests</span>
        <span>{row.total}</span>
      </p>
      {SERIES.map((s) => (
        <p
          key={s.key}
          className="text-text-primary tabular-metric mt-1 flex justify-between gap-6"
        >
          <span className="text-text-secondary">{s.name}</span>
          <span>{row[s.key]}</span>
        </p>
      ))}
      <p className="text-text-primary tabular-metric mt-1.5 flex justify-between gap-6">
        <span className="text-text-secondary">average</span>
        <span>
          {row.avgLatencyMs === null ? "no data" : `${row.avgLatencyMs} ms`}
        </span>
      </p>
      <p className="text-text-primary tabular-metric mt-1 flex justify-between gap-6">
        <span className="text-text-secondary">p95</span>
        <span>
          {row.p95LatencyMs === null ? "no data" : `${row.p95LatencyMs} ms`}
        </span>
      </p>
    </div>
  );
}

function Unavailable({ children }: { children: string }) {
  return (
    <p className="border-border bg-background-elevated/60 text-text-secondary max-w-3xl rounded-lg border p-5 text-base leading-relaxed">
      {children}
    </p>
  );
}

/**
 * The stored one-minute throughput buckets, drawn as they were persisted.
 * Provenance is HISTORICAL: rows read from the metrics view when the page
 * loaded, never updated by the stream. Only minutes that had a request have a
 * bucket, so the bars sit on a category axis in time order with their real
 * timestamps in the tooltip and table. Nothing is filled in between them and
 * nothing is smoothed. A missing, offline or empty history says so.
 */
export function PersistedThroughput({
  history,
}: {
  history: ThroughputHistory | null;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const now = useNow();

  if (history === null) {
    return (
      <Unavailable>
        Stored history is not available. The gateway did not return it, so
        nothing is drawn.
      </Unavailable>
    );
  }
  if (!history.risingwave_connected) {
    return (
      <Unavailable>
        The metrics store is offline, so no stored buckets can be read. This is
        a missing reading, not a quiet system.
      </Unavailable>
    );
  }
  const rows = historyRows(history.buckets);
  if (rows.length === 0) {
    return <Unavailable>No one-minute bucket has been stored yet.</Unavailable>;
  }

  return (
    <div>
      <p className="text-text-tertiary text-sm">
        Read {formatUtc(history.generated_at)} when this page loaded
        {now !== null ? `, ${relativeTime(history.generated_at, now)}` : ""}.
        Newest stored bucket ended{" "}
        {history.window_end
          ? formatUtc(history.window_end)
          : "at an unknown time"}
        .
      </p>

      <ul className="text-text-secondary mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {SERIES.map((s) => (
          <li key={s.key} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="h-3 w-3 rounded-sm"
              style={{ background: s.color }}
            />
            {s.name}
          </li>
        ))}
      </ul>

      <div
        className="mt-2 h-56"
        role="img"
        aria-label={`Requests per stored one-minute bucket, split by success, blocked and error. ${rows.length} ${rows.length === 1 ? "bucket" : "buckets"}, from ${rows[0].label} to ${rows[rows.length - 1].label} UTC.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid
              stroke="var(--border)"
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="label"
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--border-strong)" }}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={44}
              allowDecimals={false}
            />
            <Tooltip
              cursor={{ fill: "rgb(255 255 255 / 0.05)" }}
              content={<HistoryTooltip />}
              animationDuration={140}
            />
            {SERIES.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                stackId="requests"
                fill={s.color}
                maxBarSize={24}
                radius={i === SERIES.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={!reducedMotion}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="text-text-secondary mt-5 max-w-3xl text-base leading-relaxed">
        {rows.length} stored {rows.length === 1 ? "bucket" : "buckets"} covering{" "}
        {historyRequestTotal(rows)} requests, from{" "}
        {formatUtc(history.window_start ?? rows[0].key)} to{" "}
        {formatUtc(history.window_end ?? rows[rows.length - 1].key)}. Only
        minutes with at least one request have a bucket, so the bars are in time
        order but not evenly spaced in time. Nothing is filled in between them.
      </p>

      <details className="mt-3">
        <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-sm underline underline-offset-4">
          View the stored buckets as a table
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full max-w-3xl text-left text-sm">
            <caption className="sr-only">
              Stored one-minute throughput buckets, oldest first
            </caption>
            <thead>
              <tr className="text-text-tertiary">
                <th className="py-2 pr-4 font-normal">Bucket started (UTC)</th>
                <th className="py-2 text-right font-normal">Requests</th>
                <th className="py-2 text-right font-normal">Success</th>
                <th className="py-2 text-right font-normal">Blocked</th>
                <th className="py-2 text-right font-normal">Error</th>
                <th className="py-2 text-right font-normal">Avg ms</th>
                <th className="py-2 text-right font-normal">p95 ms</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-border border-t">
                  <td className="tabular-metric text-text-secondary py-2 pr-4 whitespace-nowrap">
                    {r.label}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.total}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.success}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.blocked}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.error}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.avgLatencyMs ?? "no data"}
                  </td>
                  <td className="tabular-metric text-text-primary py-2 text-right">
                    {r.p95LatencyMs ?? "no data"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
