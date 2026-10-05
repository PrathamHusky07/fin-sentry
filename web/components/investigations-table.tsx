import { JudgeStateBadge } from "@/components/judge-state-badge";
import type { TraceListItem } from "@/lib/trace-api";

/**
 * The real trace table. A controlled scroll region (max-height + overflow)
 * so the header can be sticky within it -- the page itself does not scroll
 * the header away. Distinct trace executions are never deduplicated: four
 * firings of the same question are four real rows.
 */
export function InvestigationsTable({
  traces,
  onSelect,
}: {
  traces: TraceListItem[];
  onSelect: (appTraceId: string) => void;
}) {
  return (
    <div className="border-border max-h-[32rem] overflow-y-auto rounded-md border">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-border bg-background-elevated text-text-secondary sticky top-0 border-b text-xs tracking-wide uppercase">
            <th className="px-3 py-2 font-medium">Time</th>
            <th className="px-3 py-2 font-medium">Query</th>
            <th className="px-3 py-2 font-medium">Ticker</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Judge state</th>
            <th className="px-3 py-2 font-medium">Frontier</th>
          </tr>
        </thead>
        <tbody>
          {traces.map((trace) => (
            <tr
              key={trace.app_trace_id}
              onClick={() => onSelect(trace.app_trace_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(trace.app_trace_id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={`View trace: ${trace.query}`}
              className="border-border hover:bg-surface focus-visible:outline-accent bg-background-elevated cursor-pointer border-b outline-none last:border-b-0 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2"
            >
              <td className="text-text-secondary px-3 py-2 whitespace-nowrap">
                {new Date(trace.timestamp_utc).toLocaleString()}
              </td>
              <td className="text-text-primary max-w-xs truncate px-3 py-2">
                {trace.query}
              </td>
              <td className="text-text-secondary px-3 py-2">
                {trace.ticker ?? "—"}
              </td>
              <td className="text-text-secondary px-3 py-2">
                {trace.rag_status}
                {trace.block_reason ? ` (${trace.block_reason})` : ""}
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
  );
}
