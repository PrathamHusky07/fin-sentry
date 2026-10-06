import type { JudgeState } from "@/lib/trace-api";

/**
 * The five-state judge model, visually distinct and never collapsed (see
 * ../CLAUDE.md). blocked_before_evaluation uses the informational color,
 * not failure -- it means the RAG request was blocked before there was
 * anything to judge, never that the judge itself erred. judge_failed is
 * deliberately not styled with the failure/red color either: it means the
 * judge pipeline itself errored out (a Gemini outage) on a request that
 * succeeded -- an operational event to investigate, not a guardrail or
 * security block. It gets its own accent-colored, dashed treatment so it
 * never reads as either "evaluated" or "blocked."
 */
const STATE_STYLE: Record<JudgeState, string> = {
  evaluated: "bg-positive/10 text-positive border-positive/40",
  partially_evaluated: "bg-warning/10 text-warning border-warning/40",
  blocked_before_evaluation: "bg-info/10 text-info border-info/40",
  judge_failed: "bg-accent/10 text-accent border-accent/40 border-dashed",
  never_evaluated:
    "text-text-secondary border-border border-dashed bg-transparent",
};

const STATE_LABEL: Record<JudgeState, string> = {
  evaluated: "Evaluated",
  partially_evaluated: "Partially evaluated",
  blocked_before_evaluation: "Blocked before evaluation",
  judge_failed: "Judge pipeline error",
  never_evaluated: "Not yet evaluated",
};

export function JudgeStateBadge({ state }: { state: JudgeState }) {
  return (
    <span
      className={`inline-flex w-fit items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${STATE_STYLE[state]}`}
    >
      {STATE_LABEL[state]}
    </span>
  );
}
