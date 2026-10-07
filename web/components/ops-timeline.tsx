import Link from "next/link";
import { StatusDot } from "@/components/status-dot";
import { outcomeLabel, outcomeTone } from "@/lib/labels";
import type { TraceListItem } from "@/lib/trace-api";

function utcClock(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

function utcDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * The newest persisted executions as a compact timeline: time, outcome, and
 * the question. It is a few lines of orientation, not a second
 * Investigations table, and every line links to its trace. Timestamps are
 * UTC so the server and the browser render the same text.
 */
export function OpsTimeline({ traces }: { traces: TraceListItem[] | null }) {
  if (traces === null) {
    return (
      <p className="border-failure/40 bg-failure/5 text-text-primary rounded-lg border p-5 text-base">
        The recent execution list is not available. The gateway did not return
        it.
      </p>
    );
  }
  if (traces.length === 0) {
    return (
      <p className="border-border text-text-secondary border-y py-8 text-base">
        No executions are persisted yet.
      </p>
    );
  }

  return (
    <ol className="border-border-strong relative ml-1 border-l">
      {traces.map((trace, i) => {
        const day = utcDay(trace.timestamp_utc);
        const showDay = i === 0 || day !== utcDay(traces[i - 1].timestamp_utc);
        const tone = outcomeTone(trace.rag_status);
        return (
          <li key={trace.app_trace_id} className="relative">
            {showDay ? <p className="eyebrow py-3 pl-6">{day}, UTC</p> : null}
            <Link
              href={`/investigations?trace=${trace.app_trace_id}`}
              className="hover:bg-surface/60 grid min-h-11 grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-0.5 rounded-md py-2 pr-2 pl-6 transition-colors sm:grid-cols-[5.5rem_14rem_1fr]"
            >
              <span className="bg-background absolute -left-[5px] mt-1.5 rounded-full">
                <StatusDot color={tone === "neutral" ? "neutral" : tone} />
              </span>
              <span className="tabular-metric text-text-tertiary text-sm">
                {utcClock(trace.timestamp_utc)}
              </span>
              <span className="text-text-primary text-sm font-medium">
                {outcomeLabel(trace.rag_status, trace.block_reason)}
              </span>
              <span className="text-text-secondary col-span-2 min-w-0 truncate text-sm sm:col-span-1">
                {trace.ticker ? (
                  <span className="text-text-tertiary mr-2 font-mono">
                    {trace.ticker}
                  </span>
                ) : null}
                {trace.query}
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
