import Link from "next/link";
import type { CSSProperties } from "react";
import { CalibrationScale } from "@/components/calibration-scale";
import { StatusDot, type StatusColor } from "@/components/status-dot";
import { Tip } from "@/components/tip";
import { formatUtc, relativeTime } from "@/lib/format";
import type { AttentionItem, AttentionTone } from "@/lib/attention";
import {
  CALIBRATION_POSITION_LABEL,
  CALIBRATION_POSITION_TONE,
} from "@/lib/labels";
import type { OverviewData } from "@/lib/overview-data";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

type StateTone = AttentionTone | "clear" | "unknown";

const TONE_TEXT: Record<StateTone, string> = {
  failure: "text-failure",
  disagreement: "text-disagreement",
  warning: "text-warning",
  info: "text-info",
  clear: "text-positive",
  unknown: "text-text-secondary",
};

const TONE_VAR: Record<StateTone, string> = {
  failure: "var(--failure)",
  disagreement: "var(--disagreement)",
  warning: "var(--warning)",
  info: "var(--info)",
  clear: "var(--positive)",
  unknown: "var(--text-tertiary)",
};

const TONE_DOT: Record<StateTone, StatusColor> = {
  failure: "failure",
  disagreement: "disagreement",
  warning: "warning",
  info: "info",
  clear: "positive",
  unknown: "neutral",
};

const CAL_TEXT = {
  positive: "text-positive",
  warning: "text-warning",
  failure: "text-failure",
  info: "text-info",
} as const;

const CAL_VAR = {
  positive: "var(--positive)",
  warning: "var(--warning)",
  failure: "var(--failure)",
  info: "var(--info)",
} as const;

/** The figure is the primary object, so it scales down with its length
 * rather than wrapping: "6" is huge, "1.000 vs 0.000" is large. */
function figureSize(figure: string): string {
  if (figure.length <= 3) return "text-8xl sm:text-9xl";
  if (figure.length <= 7) return "text-7xl sm:text-8xl";
  return "text-5xl sm:text-7xl";
}

/**
 * The frontier judge's trust state at a glance. It answers one question,
 * "can the second opinion be trusted right now", and links to the full
 * instrument on Live Operations. An unavailable reading is stated as
 * unavailable and is never drawn as healthy.
 */
function CalibrationSummary({
  calibration,
}: {
  calibration: CalibrationHealthResponse | null;
}) {
  const tone = calibration
    ? CALIBRATION_POSITION_TONE[calibration.position]
    : null;
  return (
    <Link
      href="/operations#calibration"
      className="lift reveal-host border-line-hover bg-background-elevated/80 block rounded-xl border p-6"
      style={tone ? ({ "--tone": CAL_VAR[tone] } as CSSProperties) : undefined}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-text-primary text-base font-semibold">
            Frontier judge agreement
          </h3>
          <p className="text-text-tertiary mt-0.5 text-sm">
            Can the second opinion be trusted right now?
          </p>
        </div>
        {calibration && tone ? (
          <span
            className={`tabular-metric text-3xl font-semibold ${CAL_TEXT[tone]}`}
          >
            {calibration.kappa !== null ? calibration.kappa.toFixed(3) : "n/a"}
          </span>
        ) : null}
      </div>
      {calibration && tone ? (
        <>
          <p className={`mt-3 text-sm font-medium ${CAL_TEXT[tone]}`}>
            {CALIBRATION_POSITION_LABEL[calibration.position]}
          </p>
          <p className="text-text-tertiary mt-0.5 text-sm">
            {calibration.state ?? "no state"}
            {calibration.state_as_of
              ? `, manual reading ${formatUtc(calibration.state_as_of)}`
              : ""}
          </p>
          <CalibrationScale calibration={calibration} compact />
        </>
      ) : (
        <p className="text-text-secondary mt-3 text-base">
          Calibration unavailable. The reading could not be loaded, so the
          frontier judge’s agreement is unknown.
        </p>
      )}
      <span className="text-accent nudge mt-4 inline-flex min-h-6 items-center gap-1.5 text-sm font-medium">
        Open the full instrument
        <span aria-hidden="true">→</span>
      </span>
    </Link>
  );
}

/**
 * The top of the command center. The headline figure is the most severe
 * signal's own number, set large over a field tinted with that state, and
 * the sentence under it says what it counts. Beside it the frontier judge's
 * trust summary and two small counts say what the state rests on. Nothing
 * here is a live number; each reading names its source.
 */
export function SystemState({
  overview,
  calibration,
  items,
}: {
  overview: OverviewData | null;
  calibration: CalibrationHealthResponse | null;
  items: AttentionItem[];
}) {
  const tone: StateTone = !overview
    ? "unknown"
    : items.length === 0
      ? "clear"
      : items[0].tone;

  const figure = !overview ? "n/a" : items.length === 0 ? "0" : items[0].figure;
  const figureNote = !overview
    ? "trace service unavailable"
    : items.length === 0
      ? "conditions need attention"
      : items[0].figureNote;

  const headline = !overview
    ? "The trace service is unavailable"
    : items.length === 0
      ? "No conditions need attention"
      : items[0].title;

  const subline = !overview
    ? "Counts could not be loaded from the gateway, so nothing is shown instead of a guess."
    : items.length === 0
      ? `Derived from ${overview.scanIsWindow ? "the latest " : ""}${overview.totalRequests} persisted executions. Every source loaded and no rule fired.`
      : `${items.length === 1 ? "The only condition" : `One of ${items.length} conditions`}, ranked by severity. Derived from ${overview.scanIsWindow ? "the latest " : ""}${overview.totalRequests} persisted executions${overview.latestTimestamp ? `, the newest ${relativeTime(overview.latestTimestamp)}` : ""}.`;

  return (
    <section
      aria-label="System state"
      className="grid gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]"
    >
      <div
        className="state-field self-center"
        style={{ "--field": TONE_VAR[tone] } as CSSProperties}
      >
        <p
          className={`flex items-center gap-2 text-sm font-medium ${TONE_TEXT[tone]}`}
        >
          <StatusDot color={TONE_DOT[tone]} />
          System state
        </p>
        <p
          className={`tabular-metric mt-4 leading-[0.95] font-semibold tracking-tighter ${figureSize(figure)} ${TONE_TEXT[tone]}`}
        >
          {figure}
        </p>
        <p className="text-text-secondary mt-3 text-base">{figureNote}</p>
        <h2 className="text-text-primary mt-8 max-w-xl text-2xl leading-tight font-semibold tracking-tight text-balance sm:text-3xl">
          {headline}
        </h2>
        <p className="text-text-secondary mt-4 max-w-xl text-base leading-relaxed">
          {subline}
        </p>
      </div>

      <div className="space-y-4 self-center">
        <CalibrationSummary calibration={calibration} />
        <dl className="border-line grid grid-cols-2 gap-x-6 rounded-xl border px-6 py-5">
          <div>
            <dt className="text-text-secondary text-sm">
              <Tip
                label="Delivered answers judged"
                definition="Delivered answers that have a complete or partial flash verdict, out of every delivered answer. Completion says nothing about whether the answers were right."
              >
                Delivered answers judged
              </Tip>
            </dt>
            <dd className="tabular-metric text-text-primary mt-1 text-2xl font-semibold">
              {overview
                ? `${overview.flow.deliveredComplete + overview.flow.deliveredPartial} of ${overview.flow.delivered}`
                : "not available"}
            </dd>
            <dd className="text-text-tertiary mt-0.5 text-xs">
              complete or partial flash verdict
            </dd>
          </div>
          <div>
            <dt className="text-text-secondary text-sm">
              <Tip
                label="Judge tiers in disagreement"
                definition="Executions where the flash and frontier faithfulness scores differ by 0.5 or more. Only sampled answers have a frontier score."
              >
                Judge tiers in disagreement
              </Tip>
            </dt>
            <dd className="tabular-metric text-disagreement mt-1 text-2xl font-semibold">
              {overview
                ? `${overview.disagreementTraces.length}${overview.disagreementIsWindow ? "+" : ""}`
                : "not available"}
            </dd>
            <dd className="text-text-tertiary mt-0.5 text-xs">
              {overview?.disagreementIsWindow
                ? "scores 0.5 apart or more, the query hit its limit"
                : "scores 0.5 apart or more"}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
