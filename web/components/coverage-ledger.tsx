"use client";

import Link from "next/link";
import { useState, type CSSProperties, type PointerEvent } from "react";
import { JUDGE_STATE_LABEL } from "@/components/judge-state-badge";
import { JUDGE_STATE_MEANING } from "@/lib/labels";
import type { JudgeStateCounts } from "@/lib/overview-data";
import type { JudgeState } from "@/lib/trace-api";

const ORDER: { key: JudgeState; swatch: string }[] = [
  { key: "evaluated", swatch: "bg-positive" },
  { key: "partially_evaluated", swatch: "bg-warning" },
  { key: "blocked_before_evaluation", swatch: "bg-info" },
  { key: "judge_failed", swatch: "bg-accent" },
  { key: "never_evaluated", swatch: "bg-text-tertiary" },
];

/** Widest row of squares in a group. Wider groups wrap on this grid, so
 * every group is a tidy block and area still reads as share. */
const MAX_COLS = 20;
const SQUARE = 14;
const GAP = 3;

/**
 * How far evaluation reached, drawn as the data itself: one square per
 * persisted execution, grouped by judge state, so each group's area is its
 * share. Pointing at or focusing a group brightens it, dims the rest and
 * explains the state; selecting it opens the executions it counts.
 * Completion is not quality: a field of "evaluated" squares would still say
 * nothing about whether the answers were right.
 */
export function CoverageLedger({ counts }: { counts: JudgeStateCounts }) {
  const [active, setActive] = useState<JudgeState | null>(null);
  const total = ORDER.reduce((sum, row) => sum + counts[row.key], 0);
  const summary = ORDER.map(
    (row) => `${counts[row.key]} ${JUDGE_STATE_LABEL[row.key].toLowerCase()}`,
  ).join(", ");

  return (
    <section aria-labelledby="coverage-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="coverage-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Evaluation coverage
        </h2>
        <p className="text-text-tertiary text-sm">
          One square is one of {total} persisted executions.
        </p>
      </div>

      <ul
        aria-label={`Judge state across ${total} executions: ${summary}.`}
        className="mt-8 grid gap-x-12 gap-y-10"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(min(${(MAX_COLS * (SQUARE + GAP)) / 16 + 1.5}rem, 100%), 1fr))`,
        }}
      >
        {ORDER.map((row, i) => {
          const count = counts[row.key];
          const share = total > 0 ? (count / total) * 100 : 0;
          const cols = Math.max(1, Math.min(count, MAX_COLS));
          const isActive = active === row.key;
          const dimmed = active !== null && !isActive;
          return (
            <li
              key={row.key}
              className="enter-up max-w-full"
              style={{ "--i": i } as CSSProperties}
            >
              <Link
                href={`/investigations?judge_state=${row.key}`}
                onPointerEnter={(e: PointerEvent) => {
                  if (e.pointerType === "mouse") setActive(row.key);
                }}
                onPointerLeave={(e: PointerEvent) => {
                  if (e.pointerType === "mouse") setActive(null);
                }}
                onFocus={(e) => {
                  if (e.currentTarget.matches(":focus-visible")) {
                    setActive(row.key);
                  }
                }}
                onBlur={() => setActive(null)}
                data-active={isActive}
                className={`reveal-host -m-3 block rounded-xl p-3 transition-[opacity,background-color] duration-[var(--dur-base)] ease-[var(--ease-soft)] ${
                  dimmed ? "opacity-35" : "opacity-100"
                } ${isActive ? "bg-surface-hover/70" : ""}`}
              >
                <span className="flex items-baseline gap-3">
                  <span className="tabular-metric text-text-primary text-3xl font-semibold">
                    {count}
                  </span>
                  <span className="text-text-primary text-base font-medium">
                    {JUDGE_STATE_LABEL[row.key]}
                  </span>
                  <span className="text-text-tertiary text-xs">
                    {share.toFixed(share > 0 && share < 10 ? 1 : 0)}%
                  </span>
                </span>
                <span
                  aria-hidden="true"
                  className={`mt-3 grid transition-[filter] duration-[var(--dur-base)] ${isActive ? "brightness-125" : ""}`}
                  style={{
                    gridTemplateColumns: `repeat(${cols}, ${SQUARE}px)`,
                    gap: GAP,
                  }}
                >
                  {Array.from({ length: count }, (_, n) => (
                    <span
                      key={n}
                      className={`h-3.5 w-3.5 rounded-[3px] ${row.swatch}`}
                    />
                  ))}
                </span>
                <span
                  className="reveal-on-hover text-text-secondary mt-3 block text-sm leading-snug"
                  style={{ maxWidth: Math.max(17 * 16, cols * (SQUARE + GAP)) }}
                >
                  {JUDGE_STATE_MEANING[row.key]}
                  <span className="text-accent mt-1.5 flex items-center gap-1.5 font-medium">
                    Open these executions
                    <span aria-hidden="true">→</span>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
