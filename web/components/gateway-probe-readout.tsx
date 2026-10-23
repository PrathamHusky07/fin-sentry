import { formatUtc, relativeTime } from "@/lib/format";
import type { GatewayHealthCheck } from "@/lib/gateway-health";
import {
  formatMs,
  isLoopbackTarget,
  type GatewayProbeSummary,
} from "@/lib/gateway-probe";

/**
 * The gateway health-route round trip, a supporting instrument. The recorded figure comes from a
 * stored probe run, so it is still here when nothing has run since, and it carries the time it
 * was recorded. The route runs no retrieval and no model, so the figure says how long reaching
 * the gateway takes and nothing about how long an evaluation or a RAG answer takes. The caption
 * states what was timed so a very small number cannot be read as more than that.
 */
export function GatewayProbeReadout({
  probe,
  health,
  now,
}: {
  /** The stored summary, or null when the gateway or its store did not answer. */
  probe: GatewayProbeSummary | null;
  /** The route timed by the web server for this page view, or null when it did not answer. */
  health: GatewayHealthCheck | null;
  /** Client clock, null until mounted, so the server render and the first client render agree. */
  now: number | null;
}) {
  const latest = probe?.latest ?? null;
  const state = probe === null ? "unavailable" : latest ? "recorded" : "none";

  return (
    <section aria-labelledby="gateway-heading" id="gateway">
      <h2
        id="gateway-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Gateway health route
      </h2>
      <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
        A supporting reading, separate from evaluation. It times the
        gateway&rsquo;s health route, so it measures reaching the gateway and
        not how long an evaluation or an answer takes.
      </p>

      <div
        data-gateway-probe={state}
        className="instrument enter-up bg-background-elevated/70 mt-6 rounded-xl"
        style={
          { "--tone": "var(--signal)", "--lift": "2px" } as React.CSSProperties
        }
      >
        <div className="px-6 py-6">
          <h3 className="text-text-secondary text-base sm:text-sm">
            Health-route round trip, recorded probe
          </h3>
          {latest ? (
            <>
              <p className="tabular-metric text-text-primary mt-2 text-4xl font-semibold tracking-tighter">
                {formatMs(latest.median_ms)}
                <span className="text-text-tertiary ml-2 text-base font-normal tracking-normal">
                  ms median
                </span>
              </p>
              <ul className="tabular-metric text-text-secondary mt-3 flex flex-wrap gap-x-6 gap-y-1 text-base">
                <li>p95 {formatMs(latest.p95_ms)} ms</li>
                <li>max {formatMs(latest.max_ms)} ms</li>
                <li>{latest.samples} requests</li>
              </ul>
              <p className="text-text-tertiary mt-4 max-w-3xl text-base leading-snug sm:text-sm">
                Recorded {formatUtc(latest.measured_at)}
                {now !== null
                  ? `, ${relativeTime(latest.measured_at, now)}`
                  : ""}
                . It is stored, so it stays here until the next run replaces it.
              </p>
              <p className="text-text-tertiary mt-2 max-w-3xl text-base leading-snug sm:text-sm">
                Each request was timed from the probe sending a GET to the
                gateway health route until it had read the whole response, over
                one kept-open connection and after two warm-up requests.
                {isLoopbackTarget(latest.target)
                  ? " The probe ran on the same machine as the gateway, so no network distance is in the figure."
                  : ""}{" "}
                The route runs no retrieval and no model.
              </p>
            </>
          ) : (
            <p className="text-text-secondary mt-2 max-w-3xl text-base leading-snug">
              {state === "none"
                ? "No gateway probe has been recorded. Run python -m finsentry.observability.gateway_probe to store one."
                : "The probe store did not answer, so no recorded round trip is shown. Nothing is shown in its place."}
            </p>
          )}
        </div>
        <div
          data-gateway-health={health ? "measured" : "not-measured"}
          className="border-border flex flex-col gap-1 border-t px-6 py-4 sm:flex-row sm:items-baseline sm:gap-6"
        >
          <p className="text-text-secondary shrink-0 text-sm">
            Checked just now by this page
            <span className="tabular-metric text-text-primary ml-3 text-lg font-semibold">
              {health ? `${health.medianMs} ms` : "not measured"}
            </span>
          </p>
          <p className="text-text-tertiary text-sm leading-snug">
            {health
              ? `Median of ${health.samples} requests to the gateway health route, timed by the web server at ${formatUtc(health.measuredAt)} and not stored. It runs no retrieval and no model, so it is the cost of reaching the gateway and not evaluation or request latency.`
              : "The gateway health route did not answer within its time budget, so no round trip was timed. Nothing is shown in its place."}
          </p>
        </div>
      </div>
    </section>
  );
}
