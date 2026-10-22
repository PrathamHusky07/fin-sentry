import { formatUtc, relativeTime } from "@/lib/format";
import { formatMs, type GatewayProbeSummary } from "@/lib/gateway-probe";

/**
 * The recorded gateway round trip, the low-latency reading on Live Operations. It comes from a
 * stored probe run, so it is still here when nothing has run since, and it carries the time it
 * was recorded. It is the cost of reaching the gateway health route, which runs no retrieval and
 * no model, and the caption says so. It never shares a cell with the RAG readouts below it.
 */
export function GatewayProbeReadout({
  probe,
  now,
}: {
  /** The stored summary, or null when the gateway or its store did not answer. */
  probe: GatewayProbeSummary | null;
  /** Client clock, null until mounted, so the server render and the first client render agree. */
  now: number | null;
}) {
  const latest = probe?.latest ?? null;
  const state = probe === null ? "unavailable" : latest ? "recorded" : "none";

  return (
    <div
      data-gateway-probe={state}
      className="border-border border-b px-6 py-7"
    >
      <h3 className="text-text-secondary text-sm">
        Gateway round trip, recorded probe
      </h3>
      {latest ? (
        <>
          <p className="tabular-metric text-text-primary mt-2 text-6xl font-semibold tracking-tighter">
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
          <p className="text-text-tertiary mt-3 max-w-3xl text-sm leading-snug">
            Recorded {formatUtc(latest.measured_at)}
            {now !== null ? `, ${relativeTime(latest.measured_at, now)}` : ""}.
            The requests were timed against the gateway health route, which runs
            no retrieval and no model, so this is the cost of reaching the
            gateway and not RAG latency. It is stored, so it stays here until
            the next run replaces it.
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
  );
}
