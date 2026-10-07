import Link from "next/link";
import type { TraceDetailResponse, TraceListItem } from "@/lib/trace-api";

/**
 * The finding the second judge tier exists for, shown as one case: the
 * question, the answer the system returned, and the two faithfulness scores
 * that split on it. Everything comes from the persisted trace. When the
 * trace detail is unavailable the block says so and keeps the question and
 * the link, and never invents a score or an answer.
 */
export function FeaturedDisagreement({
  trace,
  detail,
  others,
}: {
  trace: TraceListItem;
  detail: TraceDetailResponse | null;
  others: number;
}) {
  const flash = detail?.flash?.faithfulness_score ?? null;
  const frontier = detail?.frontier.evidence?.faithfulness_score ?? null;
  const reasoning = detail?.frontier.evidence?.rubric_reasoning ?? null;
  const answer = detail?.answer ?? null;
  const scored = flash !== null && frontier !== null;

  return (
    <section
      aria-labelledby="featured-heading"
      className="border-disagreement/40 bg-disagreement/[0.05] rounded-2xl border p-6 sm:p-8"
    >
      <p className="text-disagreement text-sm font-medium">
        The case the second judge exists for
      </p>
      <h2
        id="featured-heading"
        className="text-text-primary mt-2 max-w-3xl text-2xl font-semibold tracking-tight text-balance sm:text-3xl"
      >
        {trace.query}
      </h2>

      <div className="mt-8 grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div>
          <p className="text-text-tertiary text-sm">The system answered</p>
          {answer ? (
            <blockquote className="border-text-tertiary text-text-primary mt-2 border-l-2 pl-4 text-lg leading-relaxed whitespace-pre-line">
              {answer}
            </blockquote>
          ) : (
            <p className="text-text-secondary mt-2 text-base">
              The answer text could not be loaded for this trace.
            </p>
          )}
        </div>

        <div>
          {scored ? (
            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-text-secondary text-sm">
                  Flash judge, faithfulness
                </p>
                <p className="tabular-metric text-accent mt-1 text-5xl font-semibold tracking-tight">
                  {flash.toFixed(3)}
                </p>
              </div>
              <div>
                <p className="text-text-secondary text-sm">
                  Frontier judge, faithfulness
                </p>
                <p className="tabular-metric text-disagreement mt-1 text-5xl font-semibold tracking-tight">
                  {frontier.toFixed(3)}
                </p>
              </div>
            </div>
          ) : (
            <p className="text-text-secondary text-base">
              The two persisted scores could not be loaded for this trace.
            </p>
          )}
          {reasoning ? (
            <p className="text-text-secondary mt-5 text-base leading-relaxed">
              <span className="text-text-tertiary block text-sm">
                The frontier judge’s reasoning
              </span>
              {reasoning}
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
        <Link
          href={`/investigations?trace=${trace.app_trace_id}`}
          className="bg-text-primary text-background hover:bg-text-primary/90 inline-flex min-h-11 items-center rounded-lg px-5 text-sm font-medium transition-colors"
        >
          Open the full trace
        </Link>
        {others > 0 ? (
          <Link
            href="/investigations?disagreement=true"
            className="text-accent hover:text-text-primary min-h-11 content-center text-sm underline underline-offset-4"
          >
            {others} more {others === 1 ? "disagreement" : "disagreements"}
          </Link>
        ) : null}
      </div>
    </section>
  );
}
