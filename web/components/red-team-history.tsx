"use client";

import { useState } from "react";
import {
  ExpectationChip,
  RedTeamOutcomeBadge,
} from "@/components/red-team-badges";
import { formatUtcSeconds, shortId } from "@/lib/format";
import {
  CHANGE_LABEL,
  isSafetyBoundSkip,
  streakChanges,
  streaks,
  type ExecutionRecord,
} from "@/lib/red-team";

function span(first: ExecutionRecord, last: ExecutionRecord): string {
  const a = first.started_at ? formatUtcSeconds(first.started_at) : "Queued";
  if (first.execution_id === last.execution_id) return `${a} UTC`;
  const b = last.started_at ? formatUtcSeconds(last.started_at) : "Queued";
  return `${a} to ${b} UTC`;
}

/**
 * One scenario's recorded executions, newest result first. Repeated identical results
 * collapse into one line with a count and the dates they span, and a line that follows a
 * different result carries the change that led into it, such as "Caught before, missed now".
 * Every execution is still one tap away and opens its own evidence.
 */
export function RedTeamHistory({
  executions,
  onOpen,
}: {
  /** Oldest first. */
  executions: ExecutionRecord[];
  onOpen: (executionId: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const list = streaks(executions);
  const changes = streakChanges(list);
  if (list.length === 0) {
    return (
      <p className="text-text-secondary text-base sm:text-sm">
        No execution is stored for this scenario.
      </p>
    );
  }
  return (
    <ol className="space-y-3">
      {list
        .map((s, i) => ({ s, change: changes[i], key: `${s.key}#${i}` }))
        .reverse()
        .map(({ s, change, key }) => {
          const many = s.executions.length > 1;
          const expanded = open.has(key);
          return (
            <li
              key={key}
              className="border-border bg-background-elevated/50 rounded-lg border p-3"
            >
              {change ? (
                <p
                  className={`mb-2 text-base font-medium sm:text-sm ${change === "regression" || change === "lost_result" || change === "expectation_lost" ? "text-failure" : "text-text-secondary"}`}
                >
                  {CHANGE_LABEL[change]}
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <RedTeamOutcomeBadge
                  outcome={s.last.outcome}
                  state={s.last.state}
                  safetyBound={isSafetyBoundSkip(s.last)}
                />
                <ExpectationChip e={s.last} />
                {many ? (
                  <span className="text-text-primary text-base font-medium tabular-nums sm:text-sm">
                    {s.executions.length} times
                  </span>
                ) : null}
                <span className="text-text-secondary text-base sm:text-sm">
                  version {s.last.scenario_version}
                </span>
              </div>
              <p className="text-text-tertiary mt-2 text-base sm:text-sm">
                {span(s.first, s.last)}
              </p>
              <div className="mt-1 flex flex-wrap gap-2">
                {many ? (
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() =>
                      setOpen((prev) => {
                        const next = new Set(prev);
                        if (!next.delete(key)) next.add(key);
                        return next;
                      })
                    }
                    className="text-accent hover:text-text-primary min-h-11 text-base underline underline-offset-4 sm:text-sm"
                  >
                    {expanded
                      ? "Hide the executions"
                      : `Show all ${s.executions.length} executions`}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => onOpen(s.last.execution_id)}
                  className="text-accent hover:text-text-primary min-h-11 text-base underline underline-offset-4 sm:text-sm"
                >
                  {many ? "Open the latest evidence" : "Open the evidence"}
                </button>
              </div>
              {many && expanded ? (
                <ul className="border-border mt-2 border-t">
                  {[...s.executions].reverse().map((e) => (
                    <li
                      key={e.execution_id}
                      className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-1"
                    >
                      <span className="text-text-secondary text-base tabular-nums sm:text-sm">
                        {e.started_at
                          ? `${formatUtcSeconds(e.started_at)} UTC`
                          : "Queued"}
                        , run {shortId(e.run_id)}
                      </span>
                      <button
                        type="button"
                        onClick={() => onOpen(e.execution_id)}
                        aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)}`}
                        className="text-accent min-h-11 min-w-11 text-base underline underline-offset-4 sm:text-sm"
                      >
                        Evidence
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
    </ol>
  );
}
