import { Panel } from "@/components/panel";
import { StatusDot } from "@/components/status-dot";
import type { JudgeStateCounts } from "@/lib/overview-data";

const ROWS: {
  key: keyof JudgeStateCounts;
  label: string;
  color: "positive" | "warning" | "info" | "accent" | "neutral";
}[] = [
  { key: "evaluated", label: "Evaluated", color: "positive" },
  {
    key: "partially_evaluated",
    label: "Partially evaluated",
    color: "warning",
  },
  {
    key: "blocked_before_evaluation",
    label: "Blocked before evaluation",
    color: "info",
  },
  {
    key: "judge_failed",
    label: "Judge pipeline error",
    color: "accent",
  },
  { key: "never_evaluated", label: "Not yet evaluated", color: "neutral" },
];

/** All-time judge-state distribution across every persisted trace -- a
 * completion signal, not a quality signal (see the data contract: whether
 * the judge ran is not whether the system is correct). */
export function JudgeStateDistribution({
  counts,
}: {
  counts: JudgeStateCounts;
}) {
  const total = ROWS.reduce((sum, row) => sum + counts[row.key], 0);

  return (
    <Panel className="p-4">
      <h2 className="text-text-primary text-sm font-semibold">
        Judge-state distribution
      </h2>
      <p className="text-text-secondary mt-1 text-xs">
        {total} persisted request{total === 1 ? "" : "s"}, all-time.
      </p>
      <ul className="mt-3 flex flex-col gap-2">
        {ROWS.map((row) => (
          <li
            key={row.key}
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span className="flex items-center gap-2">
              <StatusDot color={row.color} />
              <span className="text-text-secondary">{row.label}</span>
            </span>
            <span className="tabular-metric text-text-primary">
              {counts[row.key]}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
