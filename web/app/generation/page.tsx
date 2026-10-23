import type { Metadata } from "next";
import Link from "next/link";
import { BoundsScale } from "@/components/generation/bounds-scale";
import { PageHeader } from "@/components/page-header";
import {
  GENERATION_BOUNDS,
  SCHEMA_RAIL_REASONS,
} from "@/lib/generation-bounds";
import { fetchGenerationRecord } from "@/lib/generation-data";
import { blockReasonLabel, blockReasonMeaning } from "@/lib/labels";
import { fetchTraceDetail } from "@/lib/overview-data";
import type { TraceDetailResponse } from "@/lib/trace-api";

export const metadata: Metadata = {
  title: "Generation | Fin-Sentry",
};

// Read on every request. Relative phrases such as "the newest 21h ago" are measured from now,
// and a page rendered once at build time would freeze them.
export const dynamic = "force-dynamic";

const NUMBER = new Intl.NumberFormat("en-US");

const SOURCE_NOTE = "text-text-tertiary mt-1 text-base sm:text-sm";

/**
 * How the one model call is bounded and what happens to the reply. The limits are code
 * constants and are labeled as such. The rejection counts are derived from the stored requests.
 * The example is one stored delivered answer. The duration of the model call alone is not
 * stored anywhere, so the page says that instead of showing a request latency as if it were
 * generation time. Nothing here starts a request or calls a model.
 */
export default async function GenerationPage() {
  const record = await fetchGenerationRecord();
  // The newest delivered answer that cites its sources, so the example shows the whole
  // contract. The candidates are read together and the first with citations is used.
  const candidates = record
    ? await Promise.all(record.recentDelivered.map(fetchTraceDetail))
    : [];
  const answer: TraceDetailResponse | null =
    candidates.find((d) => d?.found && d.answer && d.citations.length > 0) ??
    null;
  const b = GENERATION_BOUNDS;
  const rejectedTotal = record
    ? SCHEMA_RAIL_REASONS.reduce((sum, r) => sum + record.rejected[r], 0)
    : 0;

  return (
    <div className="ctx ctx-forensic mobile-readable flex-1">
      <div className="mx-auto w-full max-w-5xl px-4 py-12 sm:px-8 sm:py-16">
        <PageHeader eyebrow="What limits the model call?" title="Generation">
          One local model call turns the retrieved filing text into a JSON
          answer. Time limits and a circuit breaker bound the call, and the
          output schema rail checks the JSON that comes back.
        </PageHeader>

        <section
          aria-labelledby="bounds-heading"
          className="border-border mt-12 border-t pt-10"
        >
          <h2
            id="bounds-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            The bounds
          </h2>
          <p className={SOURCE_NOTE}>
            Set in code, in finsentry/gateway/main.py. These are limits, not
            measurements.
          </p>
          <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <BoundsScale />
            <dl className="space-y-5">
              <div>
                <dt className="text-text-primary text-base font-medium">
                  Call budget, {b.callBudgetSeconds} seconds
                </dt>
                <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                  All attempts at the model call share it. A failed attempt is
                  retried after a wait of 0.5 to 4 seconds, and retries stop
                  when the budget is spent.
                </dd>
              </div>
              <div>
                <dt className="text-text-primary text-base font-medium">
                  Attempt cap, {b.attemptCapSeconds} seconds
                </dt>
                <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                  One attempt never runs longer than this or longer than the
                  budget that remains. The application cancels a stalled attempt
                  itself and does not wait on the transport.
                </dd>
              </div>
              <div>
                <dt className="text-text-primary text-base font-medium">
                  Circuit breaker, {b.breakerFailures} failures
                </dt>
                <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                  After {b.breakerFailures} failed requests the breaker opens
                  for {b.breakerOpenSeconds} seconds and callers get an
                  immediate 503 instead of waiting on a model that is down. A
                  rate limit does not count as a failure.
                </dd>
              </div>
              <div>
                <dt className="text-text-primary text-base font-medium">
                  Request deadline, {b.requestDeadlineSeconds} seconds
                </dt>
                <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                  The whole request is cancelled and answered with a 504 at this
                  limit. It covers the input rails, retrieval, the model call
                  and the output rails.
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <section
          aria-labelledby="rejected-heading"
          className="border-border mt-12 border-t pt-10"
        >
          <h2
            id="rejected-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            What the schema rail rejected
          </h2>
          <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed">
            The model is asked for JSON mode, and the output schema rail still
            checks every reply against the answer contract. A reply that fails
            is blocked and stored with the reason.
          </p>
          {record === null ? (
            <p
              role="status"
              className="border-warning/50 text-text-primary mt-6 max-w-3xl rounded-lg border border-dashed p-4 text-base"
            >
              The stored requests could not be read, so no count is shown.
            </p>
          ) : (
            <>
              <p className={SOURCE_NOTE}>
                Counted from {NUMBER.format(record.total)} stored{" "}
                {record.scanIsWindow ? "(the newest) " : ""}
                requests. {NUMBER.format(record.delivered)} were delivered and{" "}
                {NUMBER.format(record.errored)} ended in an error status.
              </p>
              <p className="text-text-primary mt-4 text-lg">
                <span className="tabular-metric text-3xl font-semibold">
                  {NUMBER.format(rejectedTotal)}
                </span>{" "}
                replies were rejected by this rail.
              </p>
              <ul className="border-border divide-border mt-4 divide-y rounded-xl border">
                {SCHEMA_RAIL_REASONS.map((reason) => {
                  const count = record.rejected[reason];
                  const example = record.example[reason];
                  return (
                    <li
                      key={reason}
                      className="grid gap-x-6 gap-y-1 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
                    >
                      <div className="min-w-0">
                        <p className="text-text-primary text-base font-medium">
                          {blockReasonLabel(reason)}
                        </p>
                        <p className="text-text-secondary mt-0.5 text-base leading-snug">
                          {blockReasonMeaning(reason)}
                        </p>
                      </div>
                      <div className="flex items-center gap-4 sm:justify-end">
                        <span className="tabular-metric text-text-primary text-2xl font-semibold">
                          {NUMBER.format(count)}
                        </span>
                        {example ? (
                          <Link
                            href={`/investigations?trace=${example}`}
                            className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
                          >
                            Open the newest
                          </Link>
                        ) : (
                          <span className="text-text-tertiary text-base sm:text-sm">
                            None stored
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-3">
                <Link
                  href="/investigations?status=blocked"
                  className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
                >
                  See every blocked request, with the rail that stopped it
                </Link>
              </p>
            </>
          )}
          <p className="border-border-strong text-text-secondary mt-6 max-w-3xl rounded-lg border border-dashed p-4 text-base leading-relaxed">
            <span className="text-text-primary font-medium">Not stored.</span>{" "}
            The duration of the model call alone is not recorded. The request
            latency on Live Operations includes the rails and retrieval, so it
            is not shown here as generation time.
          </p>
        </section>

        <section
          aria-labelledby="answer-heading"
          className="border-border mt-12 border-t pt-10 pb-8"
        >
          <h2
            id="answer-heading"
            className="text-text-primary text-2xl font-semibold tracking-tight"
          >
            A delivered answer, as stored
          </h2>
          {answer ? (
            <>
              <p className={SOURCE_NOTE}>
                The newest stored reply that the schema rail accepted and that
                cites its sources, for the question “{answer.query}”.
              </p>
              <dl className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-3">
                <div>
                  <dt className="text-text-tertiary text-base sm:text-sm">
                    Model
                  </dt>
                  <dd className="text-text-primary mt-0.5 font-mono text-base break-words">
                    {answer.model_used ?? "not stored"}
                  </dd>
                </div>
                <div>
                  <dt className="text-text-tertiary text-base sm:text-sm">
                    Confidence
                  </dt>
                  <dd className="text-text-primary mt-0.5 text-base">
                    {answer.confidence ?? "not stored"}
                  </dd>
                </div>
                <div>
                  <dt className="text-text-tertiary text-base sm:text-sm">
                    Citations
                  </dt>
                  <dd className="text-text-primary tabular-metric mt-0.5 text-base">
                    {answer.citations.length}
                  </dd>
                </div>
              </dl>
              <blockquote className="border-line-hover text-text-secondary mt-5 max-w-3xl border-l-2 pl-4 text-base leading-relaxed">
                {answer.answer}
              </blockquote>
              <p className="mt-4">
                <Link
                  href={`/investigations?trace=${answer.app_trace_id}`}
                  className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
                >
                  Open the full trace
                </Link>
              </p>
            </>
          ) : (
            <p
              role="status"
              className="border-warning/50 text-text-primary mt-6 max-w-3xl rounded-lg border border-dashed p-4 text-base"
            >
              No stored delivered answer with citations could be read, so no
              example is shown.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
