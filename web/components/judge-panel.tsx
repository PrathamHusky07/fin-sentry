"use client";

import { useEffect, useState } from "react";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { TraceDrilldown } from "@/components/trace-drilldown";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceListResponse } from "@/lib/trace-api";

/**
 * The Judge Panel table: investigation-first, not a dashboard card wall.
 * Clicking a row opens the real trace drill-down (see trace-drilldown.tsx).
 */
export function JudgePanel() {
  const [data, setData] = useState<TraceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/traces?limit=50`)
      .then((res) =>
        res.ok ? (res.json() as Promise<TraceListResponse>) : null,
      )
      .then((body) => {
        if (!cancelled) {
          setData(body);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-text-primary text-2xl font-semibold tracking-tight">
        Judge Panel
      </h1>
      <p className="text-text-secondary mt-1 text-sm">
        Every persisted request, its flash-tier evaluation state, and whether
        the frontier tier sampled it. Click a row to see the full trace.
      </p>

      {loading ? (
        <p className="text-text-secondary mt-6 text-sm">Loading…</p>
      ) : null}

      {!loading && (!data || data.traces.length === 0) ? (
        <p className="text-text-secondary mt-6 text-sm">
          {data ? "No traces found." : "The trace list could not be loaded."}
        </p>
      ) : null}

      {!loading && data && data.traces.length > 0 ? (
        <div className="border-border mt-6 overflow-x-auto rounded-md border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-border text-text-secondary border-b text-xs tracking-wide uppercase">
                <th className="px-3 py-2 font-medium">Query</th>
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Judge state</th>
                <th className="px-3 py-2 font-medium">Frontier</th>
              </tr>
            </thead>
            <tbody>
              {data.traces.map((trace) => (
                <tr
                  key={trace.app_trace_id}
                  onClick={() => setSelected(trace.app_trace_id)}
                  className="border-border hover:bg-surface cursor-pointer border-b last:border-b-0"
                >
                  <td className="text-text-primary max-w-xs truncate px-3 py-2">
                    {trace.query}
                  </td>
                  <td className="text-text-secondary px-3 py-2">
                    {trace.ticker ?? "—"}
                  </td>
                  <td className="text-text-secondary px-3 py-2">
                    {trace.rag_status}
                  </td>
                  <td className="px-3 py-2">
                    <JudgeStateBadge state={trace.judge_state} />
                  </td>
                  <td className="text-text-secondary px-3 py-2">
                    {trace.frontier_sampled ? "Sampled" : "Not sampled"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        // key forces a remount per trace so the drilldown's own loading
        // state resets naturally instead of being reset inside an effect.
        <TraceDrilldown
          key={selected}
          appTraceId={selected}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}
