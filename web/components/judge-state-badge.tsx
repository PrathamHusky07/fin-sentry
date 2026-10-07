import type { JudgeState } from "@/lib/trace-api";

/**
 * The five-state judge model, visually distinct and never collapsed (see
 * ../CLAUDE.md). blocked_before_evaluation uses the informational color,
 * not failure: it means the request was stopped before there was anything
 * to judge, never that the judge erred. judge_failed is deliberately not
 * red either: the judge pipeline itself errored on a request that
 * succeeded, an operational event to investigate rather than a guardrail
 * block, so it keeps its own dashed treatment. never_evaluated is a quiet
 * dashed outline: nothing has run yet.
 */
const STATE_STYLE: Record<JudgeState, string> = {
  evaluated: "bg-positive/10 text-positive border-positive/30",
  partially_evaluated: "bg-warning/10 text-warning border-warning/30",
  blocked_before_evaluation: "bg-info/10 text-info border-info/30",
  judge_failed: "bg-accent/10 text-accent border-accent/50 border-dashed",
  never_evaluated:
    "text-text-secondary border-border-strong border-dashed bg-transparent",
};

export const JUDGE_STATE_LABEL: Record<JudgeState, string> = {
  evaluated: "Evaluated",
  partially_evaluated: "Partially evaluated",
  blocked_before_evaluation: "Blocked before evaluation",
  judge_failed: "Judge pipeline error",
  never_evaluated: "Not yet evaluated",
};

export function JudgeStateBadge({ state }: { state: JudgeState }) {
  return (
    <span
      className={`inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${STATE_STYLE[state]}`}
    >
      {JUDGE_STATE_LABEL[state]}
    </span>
  );
}
