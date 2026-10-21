import Link from "next/link";
import type { ReactNode } from "react";
import { Tip } from "@/components/tip";
import { RECORD_STATE } from "@/lib/agent-view";
import {
  HYPOTHESIS_STATUS_LABEL,
  HYPOTHESIS_STATUS_MEANING,
  QUERY_OUTCOME_LABEL,
  QUERY_OUTCOME_MEANING,
  STATUS_LABEL,
  STATUS_MEANING,
  SUBSYSTEM_LABEL,
  kindLabel,
  recordHref,
  type Confidence,
  type EvidenceRef,
  type HypothesisStatus,
  type Origin,
  type Outcome,
  type PredictionState,
  type QueryOutcome,
  type Status,
  type Subsystem,
} from "@/lib/incidents";

/**
 * One rule for every badge on the incident pages, the same one the Red Team badges use: a
 * solid border says something about the platform or the investigation, and a dashed border
 * says nothing about it. Nothing dashed is ever green.
 */
const BADGE =
  "inline-flex w-fit items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

/** The definition tooltip adds a tab stop, so a dense list renders the bare badge and the
 * detail views ask for the meaning. */
function Meaning({
  on,
  label,
  definition,
  children,
}: {
  on: boolean;
  label?: string;
  definition: string;
  children: ReactNode;
}) {
  return on ? (
    <Tip label={label} definition={definition}>
      {children}
    </Tip>
  ) : (
    <>{children}</>
  );
}

const STATUS_STYLE: Record<Status, string> = {
  running: "bg-accent/10 text-accent border-accent/40",
  completed: "text-text-secondary border-border-strong",
  failed: "bg-failure/10 text-failure border-failure/40",
  interrupted: "bg-warning/10 text-warning border-warning/40 border-dashed",
};

export function StatusBadge({
  status,
  withMeaning = false,
}: {
  status: Status;
  withMeaning?: boolean;
}) {
  return (
    <Meaning
      on={withMeaning}
      label={STATUS_LABEL[status]}
      definition={STATUS_MEANING[status]}
    >
      <span className={`${BADGE} ${STATUS_STYLE[status]}`}>
        {STATUS_LABEL[status]}
      </span>
    </Meaning>
  );
}

/** A diagnosis is a best-supported hypothesis and is never styled as a solved cause. An
 * abstention is a complete, honest outcome and is styled as one, not as an error. */
export function OutcomeBadge({ outcome }: { outcome: Outcome | null }) {
  if (outcome === null) {
    return (
      <span
        className={`${BADGE} text-text-tertiary border-border-strong border-dashed`}
      >
        No report
      </span>
    );
  }
  return outcome === "diagnosis" ? (
    <span className={`${BADGE} text-info border-info/40 bg-info/10`}>
      Best-supported hypothesis
    </span>
  ) : (
    <span
      className={`${BADGE} text-text-primary border-border-strong bg-surface`}
    >
      Abstained
    </span>
  );
}

export function OriginBadge({
  origin,
  planner,
  withMeaning = false,
}: {
  origin: Origin;
  planner: string;
  withMeaning?: boolean;
}) {
  return origin === "live" ? (
    <Meaning
      on={withMeaning}
      label={RECORD_STATE.live.label}
      definition={`${RECORD_STATE.live.meaning} Planner: ${planner}.`}
    >
      <span className={`${BADGE} text-signal border-signal/40 bg-signal/10`}>
        {RECORD_STATE.live.label}
      </span>
    </Meaning>
  ) : (
    <Meaning
      on={withMeaning}
      label={RECORD_STATE.fixture.label}
      definition={`${RECORD_STATE.fixture.meaning} Scripted planner: ${planner}.`}
    >
      <span
        className={`${BADGE} text-disagreement border-disagreement/50 border-dashed`}
      >
        {RECORD_STATE.fixture.label}
      </span>
    </Meaning>
  );
}

const HYPOTHESIS_STYLE: Record<HypothesisStatus, string> = {
  supported: "bg-info/10 text-info border-info/40",
  open: "text-text-secondary border-border-strong border-dashed",
  weakened: "bg-warning/10 text-warning border-warning/40",
  refuted: "bg-failure/10 text-failure border-failure/40",
};

export function HypothesisStatusBadge({
  status,
}: {
  status: HypothesisStatus;
}) {
  return (
    <Meaning
      on
      label={HYPOTHESIS_STATUS_LABEL[status]}
      definition={HYPOTHESIS_STATUS_MEANING[status]}
    >
      <span className={`${BADGE} ${HYPOTHESIS_STYLE[status]}`}>
        {HYPOTHESIS_STATUS_LABEL[status]}
      </span>
    </Meaning>
  );
}

const QUERY_STYLE: Record<QueryOutcome, string> = {
  returned: "text-text-secondary border-border-strong",
  verified_empty: "text-text-secondary border-border-strong border-dashed",
  unverified_empty:
    "bg-warning/10 text-warning border-warning/50 border-dashed",
  unavailable: "bg-failure/5 text-failure border-failure/50 border-dashed",
  rejected: "text-text-tertiary border-border-strong border-dashed",
};

export function QueryOutcomeBadge({ outcome }: { outcome: QueryOutcome }) {
  return (
    <Meaning
      on
      label={QUERY_OUTCOME_LABEL[outcome]}
      definition={QUERY_OUTCOME_MEANING[outcome]}
    >
      <span className={`${BADGE} ${QUERY_STYLE[outcome]}`}>
        {QUERY_OUTCOME_LABEL[outcome]}
      </span>
    </Meaning>
  );
}

const PREDICTION_STYLE: Record<PredictionState, string> = {
  met: "text-positive border-positive/40 bg-positive/10",
  unmet: "text-failure border-failure/40 bg-failure/10",
  unknown: "text-warning border-warning/50 border-dashed",
};

const PREDICTION_LABEL: Record<PredictionState, string> = {
  met: "Met",
  unmet: "Unmet",
  unknown: "Could not be checked",
};

export function PredictionBadge({ state }: { state: PredictionState }) {
  return (
    <span className={`${BADGE} ${PREDICTION_STYLE[state]}`}>
      {PREDICTION_LABEL[state]}
    </span>
  );
}

export function SubsystemChip({ subsystem }: { subsystem: Subsystem }) {
  return (
    <span
      className={`${BADGE} text-text-primary border-border-strong bg-surface`}
    >
      {SUBSYSTEM_LABEL[subsystem]}
    </span>
  );
}

const CONFIDENCE_MEANING: Record<Confidence, string> = {
  low: "Nothing ruled a rival out.",
  medium:
    "A rival was weakened, or more than one record supports it, and no rival was refuted by a record.",
  high: "A rival for the same symptom was refuted by a record and no empty result was left unverified. It is still not proof.",
};

export function ConfidenceChip({ confidence }: { confidence: Confidence }) {
  return (
    <Meaning
      on
      label={`${confidence} confidence`}
      definition={CONFIDENCE_MEANING[confidence]}
    >
      <span className={`${BADGE} text-text-secondary border-border-strong`}>
        {confidence[0].toUpperCase() + confidence.slice(1)} confidence
      </span>
    </Meaning>
  );
}

/** A cited record. It links to the page that shows it when the session read the live
 * platform, and is plain text for a fixture record or one with no page of its own. */
export function RecordChip({
  record,
  origin,
}: {
  record: EvidenceRef;
  origin: Origin;
}) {
  const href = recordHref(record, origin);
  const body = (
    <>
      <span className="text-text-tertiary">{kindLabel(record.kind)}</span>
      <span className="font-mono">{record.record_id}</span>
    </>
  );
  const cls =
    "inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 text-xs break-all";
  return href ? (
    <Link
      href={href}
      className={`${cls} border-border-strong text-text-primary hover:bg-surface min-h-11`}
    >
      {body}
      <span aria-hidden="true">→</span>
    </Link>
  ) : (
    <span className={`${cls} border-border text-text-secondary py-0.5`}>
      {body}
    </span>
  );
}
