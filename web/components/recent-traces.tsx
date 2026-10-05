import Link from "next/link";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { Panel } from "@/components/panel";
import type { TraceListItem } from "@/lib/trace-api";

/**
 * A compact, linkable trace list -- used by Overview's "Recent
 * Investigations" (the real traces worth looking at first) and Live
 * Operations' "Recent activity" (plain chronological). Never the full
 * trace dump; that's what Investigations is for.
 */
export function RecentTraces({
  title,
  description,
  traces,
}: {
  title: string;
  description: string;
  traces: TraceListItem[];
}) {
  return (
    <Panel className="p-4">
      <h2 className="text-text-primary text-sm font-semibold">{title}</h2>
      <p className="text-text-secondary mt-1 text-xs">{description}</p>

      {traces.length === 0 ? (
        <p className="text-text-secondary mt-3 text-sm">
          No traces persisted yet.
        </p>
      ) : (
        <ul className="border-border mt-3 divide-y rounded-md border">
          {traces.map((trace) => (
            <li key={trace.app_trace_id}>
              <Link
                href={`/investigations?trace=${trace.app_trace_id}`}
                className="hover:bg-surface focus-visible:outline-accent flex min-h-11 items-center gap-3 px-3 py-2 text-sm focus-visible:outline focus-visible:-outline-offset-2"
              >
                <span className="text-text-primary min-w-0 flex-1 truncate">
                  {trace.query}
                </span>
                <span className="text-text-secondary hidden shrink-0 sm:inline">
                  {trace.ticker ?? "—"}
                </span>
                <span className="shrink-0">
                  <JudgeStateBadge state={trace.judge_state} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
