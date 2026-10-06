import Link from "next/link";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { Panel } from "@/components/panel";
import { StatusDot } from "@/components/status-dot";
import type { TraceGroup } from "@/lib/overview-data";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function groupHref(group: TraceGroup): string {
  const params = new URLSearchParams({ q: group.query });
  if (group.ticker) params.set("ticker", group.ticker);
  return `/investigations?${params.toString()}`;
}

/**
 * A compact, linkable trace-group list -- used by Overview's "Recent
 * Investigations" and Live Operations' "Recent activity." Each row is a
 * representative-aggregation group (see ../lib/overview-data.ts): a group
 * of one real execution renders exactly like a plain trace row; a group of
 * more than one shows "N executions · latest Xm ago · M disagreements" and
 * links into Investigations pre-filtered to that exact (ticker, query)
 * pair, where every real execution is still an individual, un-deduplicated
 * row.
 */
export function RecentTraces({
  title,
  description,
  groups,
}: {
  title: string;
  description: string;
  groups: TraceGroup[];
}) {
  return (
    <Panel className="p-4">
      <h2 className="text-text-primary text-sm font-semibold">{title}</h2>
      <p className="text-text-secondary mt-1 text-xs">{description}</p>

      {groups.length === 0 ? (
        <p className="text-text-secondary mt-3 text-sm">
          No traces persisted yet.
        </p>
      ) : (
        <ul className="border-border mt-3 divide-y rounded-md border">
          {groups.map((group) => (
            <li key={`${group.ticker ?? ""}-${group.query}`}>
              <Link
                href={groupHref(group)}
                className="hover:bg-surface focus-visible:outline-accent flex min-h-11 items-center gap-3 px-3 py-2 text-sm transition-colors focus-visible:outline focus-visible:-outline-offset-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="text-text-primary block truncate">
                    {group.query}
                  </span>
                  {group.executionCount > 1 ? (
                    <span className="text-text-secondary mt-0.5 flex items-center gap-1.5 text-xs">
                      {group.executionCount} executions · latest{" "}
                      {relativeTime(group.latestTimestamp)}
                      {group.disagreementCount > 0 ? (
                        <span className="text-disagreement flex items-center gap-1 font-medium">
                          <StatusDot color="disagreement" />
                          {group.disagreementCount} disagreement
                          {group.disagreementCount === 1 ? "" : "s"}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </span>
                <span className="text-text-secondary hidden shrink-0 sm:inline">
                  {group.ticker ?? "—"}
                </span>
                <span className="shrink-0">
                  <JudgeStateBadge state={group.latestTrace.judge_state} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
