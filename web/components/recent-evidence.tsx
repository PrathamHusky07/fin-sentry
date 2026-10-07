import Link from "next/link";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { relativeTime } from "@/lib/format";
import { outcomeLabel } from "@/lib/labels";
import type { TraceGroup } from "@/lib/overview-data";

function groupHref(group: TraceGroup): string {
  if (group.firstDisagreementId) {
    return `/investigations?trace=${group.firstDisagreementId}`;
  }
  if (group.executionCount === 1) {
    return `/investigations?trace=${group.latestTrace.app_trace_id}`;
  }
  const params = new URLSearchParams({ q: group.query });
  if (group.ticker) params.set("ticker", group.ticker);
  return `/investigations?${params.toString()}`;
}

/**
 * Executions worth opening first: judge disagreements, then judge errors,
 * then blocked or errored requests, then the rest. Repeated identical
 * questions are grouped here and only here. Each row says how many
 * executions it stands for, and Investigations still lists every one of
 * them individually.
 */
export function RecentEvidence({ groups }: { groups: TraceGroup[] }) {
  return (
    <section aria-labelledby="evidence-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="evidence-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Recent investigations
        </h2>
        <p className="text-text-tertiary max-w-md text-sm sm:text-right">
          Disagreements and failures first. Repeated questions are grouped on
          this page only.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="border-border text-text-secondary mt-6 border-y py-8 text-base">
          No executions are persisted yet.
        </p>
      ) : (
        <ul className="border-border mt-6 border-t">
          {groups.map((group) => {
            const trace = group.latestTrace;
            const flagged = group.disagreementCount > 0;
            const failed = trace.rag_status !== "success";
            return (
              <li
                key={`${group.ticker ?? ""}-${group.query}`}
                className="border-border border-b"
              >
                <Link
                  href={groupHref(group)}
                  className="hover:bg-surface/60 relative grid min-h-11 gap-x-6 gap-y-2 py-4 pr-2 pl-5 transition-colors lg:grid-cols-[1fr_auto]"
                >
                  <span
                    aria-hidden="true"
                    className={`absolute top-4 bottom-4 left-0 w-[3px] rounded-full ${
                      flagged
                        ? "bg-disagreement"
                        : failed
                          ? "bg-warning"
                          : "bg-border-strong"
                    }`}
                  />
                  <span className="min-w-0">
                    <span className="text-text-primary block text-base font-medium">
                      {group.query}
                    </span>
                    <span className="text-text-tertiary mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                      {group.ticker ? (
                        <span className="font-mono">{group.ticker}</span>
                      ) : null}
                      <span>
                        {group.executionCount === 1
                          ? "1 execution"
                          : `${group.executionCount} executions`}
                        , latest {relativeTime(group.latestTimestamp)}
                      </span>
                      {flagged ? (
                        <span className="text-disagreement font-medium">
                          {group.disagreementCount}{" "}
                          {group.disagreementCount === 1
                            ? "disagreement"
                            : "disagreements"}
                        </span>
                      ) : null}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2 lg:justify-end">
                    <span className="text-text-secondary text-sm">
                      {outcomeLabel(trace.rag_status, trace.block_reason)}
                    </span>
                    <JudgeStateBadge state={trace.judge_state} />
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
