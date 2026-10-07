import Link from "next/link";
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

/** Columns for a roughly three-to-one block of unit squares. */
function columnsFor(count: number): number {
  return Math.max(1, Math.ceil(Math.sqrt(count * 3)));
}

/**
 * How far evaluation reached, drawn as the data itself: one square per
 * persisted execution, grouped by judge state, so each group’s area is its
 * share. Each group is also the link into the executions it counts.
 * Completion is not quality: a field of "evaluated" squares would still say
 * nothing about whether the answers were right.
 */
export function CoverageLedger({ counts }: { counts: JudgeStateCounts }) {
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
        className="mt-8 flex flex-wrap gap-x-12 gap-y-10"
      >
        {ORDER.map((row) => {
          const count = counts[row.key];
          const share = total > 0 ? (count / total) * 100 : 0;
          const cols = columnsFor(count);
          return (
            <li key={row.key} className="max-w-full">
              <Link
                href={`/investigations?judge_state=${row.key}`}
                className="group block rounded-lg p-2 -m-2 transition-colors hover:bg-surface/50"
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
                  className="mt-3 flex flex-wrap gap-[3px]"
                  style={{ maxWidth: `${cols * 17}px` }}
                >
                  {Array.from({ length: count }, (_, i) => (
                    <span
                      key={i}
                      className={`h-3.5 w-3.5 rounded-[3px] transition-transform group-hover:scale-105 ${row.swatch}`}
                    />
                  ))}
                </span>
                <span className="text-text-secondary mt-3 block max-w-[17rem] text-sm leading-snug">
                  {JUDGE_STATE_MEANING[row.key]}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
