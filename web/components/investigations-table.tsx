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

/** The row's severity: disagreement first, then blocks and errors. A
 * delivered, undisputed execution has no rail until it is pointed at. */
function rowTone(
  trace: TraceListItem,
  flagged: boolean,
): { tone: string; rail: boolean } {
  if (flagged) return { tone: "var(--disagreement)", rail: true };
  if (trace.rag_status === "blocked") {
    return { tone: "var(--warning)", rail: true };
  }
  if (trace.rag_status === "error") {
    return { tone: "var(--failure)", rail: true };
  }
  return { tone: "var(--text-tertiary)", rail: false };
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
            const flagged = disagreementIds.has(t.app_trace_id);
            const { tone, rail } = rowTone(t, flagged);
            return (
              <tr
                key={t.app_trace_id}
                onClick={() => onSelect(t.app_trace_id)}
                aria-current={selected ? "true" : undefined}
                data-rail={rail}
                data-flagged={flagged}
                style={{ "--tone": tone } as React.CSSProperties}
                className="trace-row reveal-host border-border cursor-pointer border-b"
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
                    className="flex min-h-11 w-full min-w-0 scroll-mt-28 scroll-mb-24 items-center justify-between gap-3 rounded-md text-left"
                  >
                    <span className="nudge flex min-w-0 flex-col items-start">
                      <span className="text-text-primary w-full truncate text-sm font-medium">
                        {t.query}
                      </span>
                      <span className="text-text-tertiary mt-0.5 flex items-center gap-2 font-mono text-xs">
                        {t.ticker ? (
                          <span className="text-text-secondary">
                            {t.ticker}
                          </span>
                        ) : null}
                        <span className="trace-id">
                          {shortId(t.app_trace_id)}
                        </span>
                      </span>
                    </span>
                    <span
                      aria-hidden="true"
                      className="reveal-on-hover text-accent shrink-0 pr-1 text-base"
                    >
                      →
                    </span>
                  </button>
                </td>
                <td className="px-3 py-3 align-top">
                  <span className="trace-badges inline-flex">
                    <OutcomeBadge
                      ragStatus={t.rag_status}
                      blockReason={t.block_reason}
                    />
                  </span>
                </td>
                <td className="px-3 py-3 align-top">
                  <span className="trace-badges inline-flex">
                    <JudgeStateBadge state={t.judge_state} />
                  </span>
                </td>
                <td className="px-3 py-3 align-top">
                  <span className="trace-badges inline-flex">
                    <FrontierCell trace={t} flagged={flagged} />
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <ul className="border-border border-t lg:hidden">
        {traces.map((t) => {
          const selected = t.app_trace_id === selectedTraceId;
          const flagged = disagreementIds.has(t.app_trace_id);
          const { tone, rail } = rowTone(t, flagged);
          return (
            <li
              key={t.app_trace_id}
              aria-current={selected ? "true" : undefined}
              data-rail={rail}
              data-flagged={flagged}
              style={{ "--tone": tone } as React.CSSProperties}
              className="trace-row border-border border-b"
            >
              <button
                type="button"
                data-row-button
                onClick={() => onSelect(t.app_trace_id)}
                onKeyDown={onKeyDown}
                aria-label={`Open trace: ${t.query}`}
                className="flex min-h-11 w-full scroll-mt-28 scroll-mb-24 flex-col gap-2 px-3 py-4 text-left"
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
                  <FrontierCell trace={t} flagged={flagged} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
