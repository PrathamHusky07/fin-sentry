import {
  MODE_LABEL,
  expectationLabel,
  layerLabel,
  type ExecutionRecord,
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
  "inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export type GlyphKind = Outcome | "skipped" | "pending";

/** One shape per outcome, so a state never depends on color alone. Solid strokes say
 * something about a defense (caught, missed). Dashed strokes say nothing about one. */
export function OutcomeGlyph({
  kind,
  className = "h-4 w-4",
}: {
  kind: GlyphKind;
  className?: string;
}) {
  const dashed = kind !== "caught" && kind !== "missed";
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className={`${className} shrink-0`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeDasharray={dashed ? "2.2 2" : undefined}
    >
      {kind === "caught" ? (
        <>
          <path d="M8 1.5 2.5 3.6v4c0 3.1 2.2 5.4 5.5 6.9 3.3-1.5 5.5-3.8 5.5-6.9v-4L8 1.5Z" />
          <path d="m5.4 8 1.8 1.8 3.4-3.6" strokeDasharray="none" />
        </>
      ) : kind === "missed" ? (
        <>
          <path d="M8 1.5 2.5 3.6v4c0 3.1 2.2 5.4 5.5 6.9 3.3-1.5 5.5-3.8 5.5-6.9v-4L8 1.5Z" />
          <path d="m5.9 5.9 4.2 4.2m0-4.2-4.2 4.2" strokeDasharray="none" />
        </>
      ) : kind === "evaluator_unavailable" ? (
        <>
          <circle cx="8" cy="8" r="6" />
          <path d="M6.4 5.6v4.8m3.2-4.8v4.8" strokeDasharray="none" />
        </>
      ) : kind === "execution_failed" ? (
        <>
          <path d="M8 2 14.2 13H1.8L8 2Z" />
          <path d="M8 6.4v3.1m0 1.9v.1" strokeDasharray="none" />
        </>
      ) : kind === "inconclusive" ? (
        <>
          <circle cx="8" cy="8" r="6" />
          <path
            d="M6.2 6.4a1.9 1.9 0 1 1 2.7 1.7c-.6.3-.9.7-.9 1.3m0 1.9v.1"
            strokeDasharray="none"
          />
        </>
      ) : (
        <>
          <circle cx="8" cy="8" r="6" />
          <path d="M5.4 8h5.2" strokeDasharray="none" />
        </>
      )}
    </svg>
  );
}

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
      <OutcomeGlyph kind={skipped ? "skipped" : outcome} />
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

/** How a result relates to what the scenario stored. A result that differs is amber with its
 * own glyph and a stated reason, so a caught result that is not the expected catch never reads
 * like a match. */
export function ExpectationChip({ e }: { e: ExecutionRecord }) {
  const label = expectationLabel(e);
  if (e.state !== "finished" || e.expectation === "not_assessable") {
    return (
      <span
        className={`${BADGE} text-text-tertiary border-border-strong border-dashed`}
      >
        {label}
      </span>
    );
  }
  if (e.expectation === "not_met") {
    return (
      <span className={`${BADGE} text-warning border-warning/50 bg-warning/10`}>
        <svg
          viewBox="0 0 16 16"
          aria-hidden="true"
          className="h-4 w-4 shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <path d="M3 5.5h10M3 10.5h10" />
          <path d="m11.5 3.5-7 9" />
        </svg>
        {label}
      </span>
    );
  }
  return (
    <span className={`${BADGE} text-text-secondary border-border-strong`}>
      {label}
    </span>
  );
}

/** The sentence under a differing result: what was expected and what acted. */
export function differenceText(e: ExecutionRecord): string | null {
  if (e.state !== "finished" || e.expectation !== "not_met") return null;
  if (e.outcome === "caught") {
    const expected =
      e.expected.outcome === "caught"
        ? layerLabel(e.expected.layer)
        : "no layer, as a known gap";
    return `Expected ${expected}. ${layerLabel(e.acting_layer)} acted.`;
  }
  if (e.outcome === "missed") {
    return `Expected a catch by ${layerLabel(e.expected.layer)}. The attack passed every relevant defense.`;
  }
  return null;
}
