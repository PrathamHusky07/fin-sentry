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
        className="state-field group self-center"
        style={{ "--field": TONE_VAR[tone] } as CSSProperties}
      >
        <span
          aria-hidden="true"
          className="absolute top-1 -left-3 bottom-1 w-0.5 origin-center scale-y-[0.35] rounded-full bg-[var(--field)] opacity-55 transition-[transform,opacity] duration-[var(--dur-base)] ease-[var(--ease)] group-focus-within:scale-y-100 group-focus-within:opacity-100 group-hover:scale-y-100 group-hover:opacity-100"
        />
        <p
          className={`flex items-center gap-2 text-sm font-medium ${TONE_TEXT[tone]}`}
        >
          <StatusDot color={TONE_DOT[tone]} />
          System state
        </p>
        <p
          className={`tabular-metric mt-4 origin-left leading-[0.95] font-semibold tracking-tighter transition-transform duration-[var(--dur-slow)] ease-[var(--ease)] motion-safe:group-hover:scale-[1.02] ${figureSize(figure)} ${TONE_TEXT[tone]}`}
        >
          {figure}
        </p>
        <p className="text-text-secondary mt-3 text-base">{figureNote}</p>
        <span
          aria-hidden="true"
          className="mt-7 block h-0.5 w-10 origin-left rounded-full bg-[var(--field)] opacity-70 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] group-hover:scale-x-[2.4]"
        />
        <h2 className="text-text-primary mt-6 max-w-xl text-2xl leading-tight font-semibold tracking-tight text-balance sm:text-3xl">
          {headline}
        </h2>
        <p className="text-text-secondary mt-4 max-w-xl text-base leading-relaxed">
          {subline}
        </p>
        {overview && items.length > 0 ? (
          <Link
            href={items[0].href}
            className="reveal-host text-accent hover:text-text-primary mt-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium transition-colors duration-[var(--dur-base)]"
          >
            {items[0].cta}
            <span aria-hidden="true" className="nudge inline-block">
              →
            </span>
          </Link>
        ) : null}
      </div>

      <div className="space-y-4 self-center">
        <CalibrationSummary calibration={calibration} />
        <dl className="border-line grid grid-cols-2 gap-x-3 rounded-xl border px-3 py-3 sm:px-4">
          <div
            className="row-reveal reveal-host rounded-lg px-3 py-2.5"
            style={{ "--tone": "var(--positive)" } as CSSProperties}
          >
            <dt className="text-text-secondary text-sm">
              <Tip
                className="relative z-10"
                definition="Delivered answers that have a complete or partial flash verdict, out of every delivered answer. Completion says nothing about whether the answers were right."
              >
                Delivered answers judged
              </Tip>
            </dt>
            <dd className="tabular-metric text-text-primary mt-1 text-2xl font-semibold">
              {overview ? (
                <Link
                  href="#coverage-heading"
                  className="rounded-sm after:absolute after:inset-0 after:rounded-lg"
                >
                  <span>{`${overview.flow.deliveredComplete + overview.flow.deliveredPartial} of ${overview.flow.delivered}`}</span>
                  <span className="sr-only">
                    , see evaluation coverage below
                  </span>
                </Link>
              ) : (
                "not available"
              )}
            </dd>
            <dd className="text-text-tertiary mt-0.5 text-xs">
              complete or partial flash verdict
            </dd>
            {overview ? (
              <dd
                aria-hidden="true"
                className="reveal-on-hover text-accent mt-1.5 text-xs font-medium"
              >
                See evaluation coverage ↓
              </dd>
            ) : null}
          </div>
          <div
            className="row-reveal reveal-host rounded-lg px-3 py-2.5"
            style={{ "--tone": "var(--disagreement)" } as CSSProperties}
          >
            <dt className="text-text-secondary text-sm">
              <Tip
                className="relative z-10"
                definition="Executions where the flash and frontier faithfulness scores differ by 0.5 or more. Only sampled answers have a frontier score."
              >
                Judge tiers in disagreement
              </Tip>
            </dt>
            <dd className="tabular-metric text-disagreement mt-1 text-2xl font-semibold">
              {overview ? (
                overview.disagreementTraces.length > 0 ? (
                  <Link
                    href="/investigations?disagreement=true"
                    className="rounded-sm after:absolute after:inset-0 after:rounded-lg"
                  >
                    <span>{`${overview.disagreementTraces.length}${overview.disagreementIsWindow ? "+" : ""}`}</span>
                    <span className="sr-only">
                      , open these executions in Investigations
                    </span>
                  </Link>
                ) : (
                  `0${overview.disagreementIsWindow ? "+" : ""}`
                )
              ) : (
                "not available"
              )}
            </dd>
            <dd className="text-text-tertiary mt-0.5 text-xs">
              {overview?.disagreementIsWindow
                ? "scores 0.5 apart or more, the query hit its limit"
                : "scores 0.5 apart or more"}
            </dd>
            {overview && overview.disagreementTraces.length > 0 ? (
              <dd
                aria-hidden="true"
                className="reveal-on-hover text-accent mt-1.5 text-xs font-medium"
              >
                Open these executions →
              </dd>
            ) : null}
          </div>
        </dl>
      </div>
    </section>
  );
}
