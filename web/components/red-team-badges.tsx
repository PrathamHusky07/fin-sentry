import {
  MODE_LABEL,
  MODE_MEANING,
  OUTCOME_LABEL,
  OUTCOME_MEANING,
  SAFETY_BOUND_LABEL,
  SAFETY_BOUND_MEANING,
  type ExecutionState,
  type Mode,
  type Outcome,
  type Severity,
} from "@/lib/red-team";
import { Tip } from "@/components/tip";

/**
 * Solid borders are results that say something about a defense (caught,
 * missed). Dashed borders are results that say nothing about one: the
 * evaluator could not run, the harness failed, or the evidence fell short.
 * Only caught is green, and a dashed result is never green.
 */
const OUTCOME_STYLE: Record<Outcome, string> = {
  caught: "bg-positive/10 text-positive border-positive/30",
  missed: "bg-failure/10 text-failure border-failure/40",
  evaluator_unavailable:
    "bg-warning/10 text-warning border-warning/40 border-dashed",
  execution_failed: "bg-failure/5 text-failure border-failure/40 border-dashed",
  inconclusive: "text-text-secondary border-border-strong border-dashed",
};

const BADGE =
  "inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export function RedTeamOutcomeBadge({
  outcome,
  state = "finished",
  withMeaning = false,
  safetyBound = false,
}: {
  outcome: Outcome | null;
  state?: ExecutionState;
  withMeaning?: boolean;
  /** An execution_failed result the runner skipped on purpose (isSafetyBoundSkip).
   * The persisted outcome is unchanged, only the label and meaning are. */
  safetyBound?: boolean;
}) {
  if (outcome === null) {
    return (
      <span
        className={`${BADGE} text-text-secondary border-border-strong border-dashed`}
      >
        {state === "running" ? "Running" : "Queued"}
      </span>
    );
  }
  const skipped = safetyBound && outcome === "execution_failed";
  const label = skipped ? SAFETY_BOUND_LABEL : OUTCOME_LABEL[outcome];
  const meaning = skipped ? SAFETY_BOUND_MEANING : OUTCOME_MEANING[outcome];
  const badge = (
    <span
      className={`${BADGE} ${skipped ? "text-text-secondary border-border-strong border-dashed" : OUTCOME_STYLE[outcome]}`}
    >
      {label}
    </span>
  );
  return withMeaning ? (
    <Tip label={label} definition={meaning}>
      {badge}
    </Tip>
  ) : (
    badge
  );
}

export function ModeBadge({
  mode,
  explain = true,
}: {
  mode: Mode;
  /** False inside table rows, where a tooltip trigger would add a tab stop. */
  explain?: boolean;
}) {
  const style =
    mode === "judge_assisted"
      ? "border-signal/30 bg-signal/10 text-signal"
      : "text-text-secondary border-border-strong";
  const badge = <span className={`${BADGE} ${style}`}>{MODE_LABEL[mode]}</span>;
  return explain ? (
    <Tip label={MODE_LABEL[mode]} definition={MODE_MEANING[mode]}>
      {badge}
    </Tip>
  ) : (
    badge
  );
}

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-failure/10 text-failure border-failure/30",
  high: "bg-warning/10 text-warning border-warning/30",
  medium: "text-text-secondary border-border-strong",
  low: "text-text-tertiary border-border-strong",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`${BADGE} ${SEVERITY_STYLE[severity]}`}>
      {severity[0].toUpperCase() + severity.slice(1)}
    </span>
  );
}
