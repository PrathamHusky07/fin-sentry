import { CalibrationScale } from "@/components/calibration-scale";
import { formatUtc, relativeTime } from "@/lib/format";
import type { AttentionItem, AttentionTone } from "@/lib/attention";
import type { OverviewData } from "@/lib/overview-data";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

const TONE_TEXT: Record<AttentionTone | "clear" | "unknown", string> = {
  failure: "text-failure",
  disagreement: "text-disagreement",
  warning: "text-warning",
  info: "text-info",
  clear: "text-positive",
  unknown: "text-text-secondary",
};

/**
 * The top of the command center. The headline is the most severe signal in
 * plain words, then three instruments say what the system state rests on:
 * where the frontier judge’s agreement sits against its thresholds, how
 * much of the delivered output a judge has scored, and how many answers the
 * two judge tiers split on. Nothing here is a live number; each reading
 * names its source.
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
  const tone: AttentionTone | "clear" | "unknown" = !overview
    ? "unknown"
    : items.length === 0
      ? "clear"
      : items[0].tone;

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
      className="grid gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]"
    >
      <div className="self-center">
        <p className={`text-sm font-medium ${TONE_TEXT[tone]}`}>System state</p>
        <h2 className="text-text-primary mt-3 text-4xl leading-[1.1] font-semibold tracking-tight text-balance sm:text-5xl">
          {headline}
        </h2>
        <p className="text-text-secondary mt-5 max-w-xl text-base leading-relaxed">
          {subline}
        </p>
      </div>

      <div className="border-border-strong bg-background-elevated rounded-xl border p-6">
        <h3 className="text-text-primary text-base font-semibold">
          Frontier judge agreement
        </h3>
        {calibration ? (
          <>
            <p className="text-text-tertiary mt-0.5 text-sm">
              {calibration.state ?? "no state"}
              {calibration.state_as_of
                ? `, manual reading ${formatUtc(calibration.state_as_of)}`
                : ""}
            </p>
            <CalibrationScale calibration={calibration} />
          </>
        ) : (
          <p className="text-text-secondary mt-3 text-base">
            Calibration unavailable. The reading could not be loaded, so the
            frontier judge’s agreement is unknown.
          </p>
        )}

        <dl className="border-border mt-2 grid grid-cols-2 gap-x-6 border-t pt-5">
          <div>
            <dt className="text-text-secondary text-sm">
              Delivered answers judged
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
              Judge tiers in disagreement
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
