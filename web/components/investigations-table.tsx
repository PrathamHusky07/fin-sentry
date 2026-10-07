"use client";

import { useRef } from "react";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { OutcomeBadge } from "@/components/outcome-badge";
import { formatUtcSeconds, shortId } from "@/lib/format";
import type { TraceListItem } from "@/lib/trace-api";

interface Props {
  traces: TraceListItem[];
  onSelect: (appTraceId: string) => void;
  selectedTraceId?: string | null;
  disagreementIds: Set<string>;
  busy: boolean;
}

/** A left rail that sorts the eye: disagreement first, then blocks and
 * errors. A delivered, undisputed execution gets no rail at all. */
function railClass(trace: TraceListItem, flagged: boolean): string {
  if (flagged) {
    return "bg-disagreement/[0.05] shadow-[inset_3px_0_0_var(--disagreement)]";
  }
  if (trace.rag_status === "blocked") {
    return "shadow-[inset_3px_0_0_var(--warning)]";
  }
  if (trace.rag_status === "error") {
    return "shadow-[inset_3px_0_0_var(--failure)]";
  }
  return "";
}

function FrontierCell({
  trace,
  flagged,
}: {
  trace: TraceListItem;
  flagged: boolean;
}) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {trace.frontier_sampled ? (
        <span className="border-signal/30 bg-signal/10 text-signal inline-flex rounded-md border px-2 py-0.5 text-xs font-medium">
          Sampled
        </span>
      ) : (
        <span className="text-text-tertiary text-xs">Not sampled</span>
      )}
      {flagged ? (
        <span className="border-disagreement/40 bg-disagreement/10 text-disagreement inline-flex rounded-md border px-2 py-0.5 text-xs font-medium">
          Disagreement
        </span>
      ) : null}
    </span>
  );
}

/**
 * One persisted execution per row, never grouped or deduplicated. Wide
 * screens get a real table whose header sticks just beneath the global
 * navigation. Narrower screens get the same rows as a stacked list, since a
 * five-column table at phone width would hide most of what matters. Arrow
 * keys move between rows, Enter opens one.
 */
export function InvestigationsTable({
  traces,
  onSelect,
  selectedTraceId,
  disagreementIds,
  busy,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);

  function moveFocus(e: React.KeyboardEvent, delta: number) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const buttons = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>("[data-row-button]") ?? [],
    ).filter((el) => el.offsetParent !== null);
    const index = buttons.indexOf(e.currentTarget as HTMLElement);
    const target = buttons[index + delta];
    if (target) {
      e.preventDefault();
      target.focus();
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    moveFocus(e, e.key === "ArrowDown" ? 1 : -1);
  }

  return (
    <div
      ref={rootRef}
      aria-busy={busy}
      className={busy ? "opacity-60 transition-opacity" : "transition-opacity"}
    >
      <table className="hidden w-full table-fixed text-left lg:table">
        <caption className="sr-only">
          Persisted executions, newest first. Press Enter on a row to open its
          trace.
        </caption>
        <colgroup>
          <col className="w-[10.5rem]" />
          <col />
          <col className="w-[15rem]" />
          <col className="w-[13rem]" />
          <col className="w-[9.5rem]" />
        </colgroup>
        <thead>
          <tr>
            {[
              "Time, UTC",
              "Execution",
              "Outcome",
              "Judge state",
              "Frontier",
            ].map((head) => (
              <th
                key={head}
                scope="col"
                className="text-text-tertiary bg-background border-border-strong first:pl-5 sticky top-[var(--nav-h)] z-10 border-b px-3 py-3 text-sm font-normal"
              >
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {traces.map((t) => {
            const selected = t.app_trace_id === selectedTraceId;
            return (
              <tr
                key={t.app_trace_id}
                onClick={() => onSelect(t.app_trace_id)}
                aria-current={selected ? "true" : undefined}
                className={`border-border hover:bg-surface/70 cursor-pointer border-b transition-colors ${
                  selected
                    ? "bg-accent/[0.08] shadow-[inset_3px_0_0_var(--accent)]"
                    : railClass(t, disagreementIds.has(t.app_trace_id))
                }`}
              >
                <td className="text-text-tertiary tabular-metric py-3 pr-3 pl-5 align-top text-xs whitespace-nowrap">
                  {formatUtcSeconds(t.timestamp_utc)}
                </td>
                <td className="px-3 py-1.5 align-top">
                  <button
                    type="button"
                    data-row-button
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect(t.app_trace_id);
                    }}
                    onKeyDown={onKeyDown}
                    aria-label={`Open trace: ${t.query}`}
                    className="flex min-h-11 w-full min-w-0 flex-col items-start justify-center rounded-md text-left"
                  >
                    <span className="text-text-primary w-full truncate text-sm font-medium">
                      {t.query}
                    </span>
                    <span className="text-text-tertiary mt-0.5 flex items-center gap-2 font-mono text-xs">
                      {t.ticker ? (
                        <span className="text-text-secondary">{t.ticker}</span>
                      ) : null}
                      <span>{shortId(t.app_trace_id)}</span>
                    </span>
                  </button>
                </td>
                <td className="px-3 py-3 align-top">
                  <OutcomeBadge
                    ragStatus={t.rag_status}
                    blockReason={t.block_reason}
                  />
                </td>
                <td className="px-3 py-3 align-top">
                  <JudgeStateBadge state={t.judge_state} />
                </td>
                <td className="px-3 py-3 align-top">
                  <FrontierCell
                    trace={t}
                    flagged={disagreementIds.has(t.app_trace_id)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <ul className="border-border border-t lg:hidden">
        {traces.map((t) => {
          const selected = t.app_trace_id === selectedTraceId;
          return (
            <li
              key={t.app_trace_id}
              className={`border-border border-b ${selected ? "bg-accent/[0.08] shadow-[inset_3px_0_0_var(--accent)]" : railClass(t, disagreementIds.has(t.app_trace_id))}`}
            >
              <button
                type="button"
                data-row-button
                onClick={() => onSelect(t.app_trace_id)}
                onKeyDown={onKeyDown}
                aria-label={`Open trace: ${t.query}`}
                className="hover:bg-surface/70 flex min-h-11 w-full flex-col gap-2 px-1 py-4 text-left"
              >
                <span className="text-text-primary text-base leading-snug font-medium">
                  {t.query}
                </span>
                <span className="text-text-tertiary flex flex-wrap gap-x-3 font-mono text-xs">
                  <span>{formatUtcSeconds(t.timestamp_utc)} UTC</span>
                  {t.ticker ? <span>{t.ticker}</span> : null}
                  <span>{shortId(t.app_trace_id)}</span>
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <OutcomeBadge
                    ragStatus={t.rag_status}
                    blockReason={t.block_reason}
                  />
                  <JudgeStateBadge state={t.judge_state} />
                  <FrontierCell
                    trace={t}
                    flagged={disagreementIds.has(t.app_trace_id)}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
