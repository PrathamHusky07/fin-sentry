import Link from "next/link";
import { JUDGE_STATE_LABEL } from "@/components/judge-state-badge";
import { JUDGE_STATE_MEANING } from "@/lib/labels";
import type { JudgeStateCounts } from "@/lib/overview-data";
import type { JudgeState } from "@/lib/trace-api";

const ORDER: { key: JudgeState; swatch: string; dashed?: boolean }[] = [
  { key: "evaluated", swatch: "bg-positive" },
  { key: "partially_evaluated", swatch: "bg-warning" },
  { key: "blocked_before_evaluation", swatch: "bg-info" },
  { key: "judge_failed", swatch: "bg-accent" },
  { key: "never_evaluated", swatch: "bg-text-tertiary" },
];

/**
 * How far evaluation reached across every persisted execution. One wide
 * segmented bar carries the shape, and the ledger beneath it says what each
 * state means and links to the executions in it. Completion is not quality:
 * a bar full of "evaluated" would still say nothing about whether the
 * answers were right.
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
          {total} persisted executions, by judge state.
        </p>
      </div>

      <div
        role="img"
        aria-label={`Judge state across ${total} executions: ${summary}.`}
        className="mt-6 flex h-4 gap-[3px] overflow-hidden rounded-full"
      >
        {ORDER.map((row) =>
          counts[row.key] > 0 ? (
            <span
              key={row.key}
              className={`${row.swatch} h-full first:rounded-l-full last:rounded-r-full`}
              style={{
                width: `${(counts[row.key] / total) * 100}%`,
                minWidth: 4,
              }}
            />
          ) : null,
        )}
      </div>

      <ul className="border-border mt-6 border-t">
        {ORDER.map((row) => {
          const count = counts[row.key];
          const share = total > 0 ? (count / total) * 100 : 0;
          return (
            <li key={row.key} className="border-border border-b">
              <Link
                href={`/investigations?judge_state=${row.key}`}
                className="hover:bg-surface/60 grid min-h-11 items-baseline gap-x-8 gap-y-1 px-1 py-4 transition-colors sm:grid-cols-[14rem_1fr_6.5rem] sm:px-3"
              >
                <span className="flex items-center gap-2.5">
                  <span
                    aria-hidden="true"
                    className={`h-2.5 w-2.5 shrink-0 rounded-sm ${row.swatch}`}
                  />
                  <span className="text-text-primary text-base font-medium">
                    {JUDGE_STATE_LABEL[row.key]}
                  </span>
                </span>
                <span className="text-text-secondary text-base leading-snug">
                  {JUDGE_STATE_MEANING[row.key]}
                </span>
                <span className="tabular-metric text-text-primary text-base sm:text-right">
                  {count}
                  <span className="text-text-tertiary ml-2 text-xs">
                    {share.toFixed(share > 0 && share < 10 ? 1 : 0)}%
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
