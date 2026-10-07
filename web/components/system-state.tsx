import { formatUtc, relativeTime } from "@/lib/format";
import type { AttentionItem, AttentionTone } from "@/lib/attention";
import type { OverviewData } from "@/lib/overview-data";
import type { CalibrationHealthResponse } from "@/lib/trace-api";

const TONE_RING: Record<AttentionTone | "clear" | "unknown", string> = {
  failure: "border-failure text-failure",
  disagreement: "border-disagreement text-disagreement",
  warning: "border-warning text-warning",
  info: "border-info text-info",
  clear: "border-positive text-positive",
  unknown: "border-text-tertiary text-text-secondary",
};

/**
 * The top of the command center: one sentence that answers "is something
 * wrong", sized to be read from across a room, with the three readings
 * that back it up. Nothing here is a live number; each line says what it
 * was derived from.
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
      : `${items.length} ${items.length === 1 ? "condition needs" : "conditions need"} attention`;

  const subline = !overview
    ? "Counts could not be loaded from the gateway, so nothing is shown instead of a guess."
    : `Derived from ${overview.scanIsWindow ? "the latest " : ""}${overview.totalRequests} persisted executions${overview.latestTimestamp ? `. The newest ran ${relativeTime(overview.latestTimestamp)}.` : "."}`;

  return (
    <section
      aria-label="System state"
      className="grid gap-10 lg:grid-cols-[1fr_26rem] lg:items-end"
    >
      <div className="flex items-start gap-6">
        <div
          aria-hidden="true"
          className={`flex h-20 w-20 shrink-0 items-center justify-center rounded-full border-2 font-mono text-3xl font-semibold tabular-nums ${TONE_RING[tone]}`}
        >
          {overview ? items.length : "?"}
        </div>
        <div>
          <p className="eyebrow">System state</p>
          <h2 className="text-text-primary mt-2 text-3xl leading-tight font-semibold tracking-tight text-balance sm:text-4xl">
            {headline}
          </h2>
          <p className="text-text-secondary mt-3 max-w-xl text-base leading-relaxed">
            {subline}
          </p>
        </div>
      </div>

      <dl className="divide-border border-border divide-y border-y text-sm">
        <div className="flex items-baseline justify-between gap-4 py-3">
          <dt className="text-text-secondary">Frontier calibration</dt>
          <dd className="text-right">
            <span className="text-text-primary font-medium">
              {calibration
                ? `${calibration.state ?? "no state"}${calibration.kappa !== null ? ` · κ ${calibration.kappa.toFixed(3)}` : ""}`
                : "unavailable"}
            </span>
            {calibration?.state_as_of ? (
              <span className="text-text-tertiary block text-xs">
                Manual reading, {formatUtc(calibration.state_as_of)}
              </span>
            ) : null}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-4 py-3">
          <dt className="text-text-secondary">Delivered answers judged</dt>
          <dd className="text-right">
            {overview ? (
              <>
                <span className="text-text-primary tabular-metric font-medium">
                  {overview.flow.deliveredComplete +
                    overview.flow.deliveredPartial}{" "}
                  of {overview.flow.delivered}
                </span>
                <span className="text-text-tertiary block text-xs">
                  Complete or partial flash verdict
                </span>
              </>
            ) : (
              <span className="text-text-primary font-medium">
                not available
              </span>
            )}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-4 py-3">
          <dt className="text-text-secondary">Cross-tier disagreements</dt>
          <dd className="text-right">
            <span className="text-text-primary tabular-metric font-medium">
              {overview ? overview.disagreementTraces.length : "not available"}
            </span>
            <span className="text-text-tertiary block text-xs">
              Flash and frontier scores 0.5 apart or more
            </span>
          </dd>
        </div>
      </dl>
    </section>
  );
}
