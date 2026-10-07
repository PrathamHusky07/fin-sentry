import Link from "next/link";
import type { RequestFlow as RequestFlowData } from "@/lib/overview-data";

interface Row {
  label: string;
  note?: string;
  count: number;
  bar: string;
  indent: 0 | 1 | 2;
  href?: string;
}

/**
 * The reliability pipeline as a measured funnel: every persisted request,
 * where the rails and the model path stopped some of them, and how the
 * delivered remainder stands with the flash judge. Bar width is the count
 * over all requests, so the shape is honest. A complete verdict (all three
 * metrics) and a partial one (one or two) stay separate rows because they
 * are not the same claim.
 */
export function RequestFlow({
  flow,
  frontierCount,
}: {
  flow: RequestFlowData;
  frontierCount: number;
}) {
  const rows: Row[] = [
    {
      label: "Requests received",
      count: flow.total,
      bar: "bg-text-secondary",
      indent: 0,
      href: "/investigations",
    },
    {
      label: "Stopped by input rails",
      note: "Prompt injection, hazard taxonomy or a failing input rail",
      count: flow.stoppedAt.input,
      bar: "bg-warning",
      indent: 1,
      href: "/investigations?status=blocked",
    },
    {
      label: "Stopped by the retrieval rail",
      note: "No trustworthy sources",
      count: flow.stoppedAt.retrieval,
      bar: "bg-warning",
      indent: 1,
      href: "/investigations?status=blocked",
    },
    {
      label: "Stopped by output rails",
      note: "Schema, citations, regulated phrases or faithfulness",
      count: flow.stoppedAt.output,
      bar: "bg-warning",
      indent: 1,
      href: "/investigations?status=blocked",
    },
    {
      label: "Ended in an error",
      note: "A dependency failed before an answer existed",
      count: flow.errored,
      bar: "bg-failure",
      indent: 1,
      href: "/investigations?status=error",
    },
    {
      label: "Delivered",
      note: "An answer with citations was returned",
      count: flow.delivered,
      bar: "bg-positive",
      indent: 0,
      href: "/investigations?status=success",
    },
    {
      label: "Flash verdict complete",
      note: "All three metrics scored",
      count: flow.deliveredComplete,
      bar: "bg-positive",
      indent: 1,
      href: "/investigations?judge_state=evaluated",
    },
    {
      label: "Flash verdict partial",
      note: "One or two metrics were skipped",
      count: flow.deliveredPartial,
      bar: "bg-warning",
      indent: 1,
      href: "/investigations?judge_state=partially_evaluated",
    },
    {
      label: "No flash verdict",
      note: "None persisted for a delivered answer",
      count: flow.deliveredUnjudged,
      bar: "bg-text-tertiary",
      indent: 1,
      href: "/investigations?judge_state=never_evaluated",
    },
    {
      label: "Judge pipeline error",
      count: flow.deliveredJudgeFailed,
      bar: "bg-accent",
      indent: 1,
      href: "/investigations?judge_state=judge_failed",
    },
  ];

  return (
    <section aria-labelledby="flow-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="flow-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Reliability pipeline
        </h2>
        <p className="text-text-tertiary text-sm">
          All-time counts. Bar width is the share of all requests.
        </p>
      </div>

      <ul className="border-border mt-6 border-t">
        {rows.map((row) => (
          <li key={row.label} className="border-border border-b">
            <Link
              href={row.href ?? "/investigations"}
              className="hover:bg-surface/60 grid min-h-11 items-center gap-x-6 gap-y-2 px-1 py-3.5 transition-colors sm:grid-cols-[17rem_1fr_3.5rem] sm:px-3"
            >
              <span
                className="min-w-0"
                style={{ paddingLeft: `${row.indent * 1.25}rem` }}
              >
                <span
                  className={`block text-base ${row.indent === 0 ? "text-text-primary font-semibold" : "text-text-secondary"}`}
                >
                  {row.label}
                </span>
                {row.note ? (
                  <span className="text-text-tertiary block text-xs leading-snug">
                    {row.note}
                  </span>
                ) : null}
              </span>
              <span
                aria-hidden="true"
                className="bg-surface block h-2 overflow-hidden rounded-full"
              >
                <span
                  className={`block h-full rounded-full ${row.bar}`}
                  style={{
                    width: `${flow.total > 0 ? (row.count / flow.total) * 100 : 0}%`,
                    minWidth: row.count > 0 ? 3 : 0,
                  }}
                />
              </span>
              <span className="tabular-metric text-text-primary text-base sm:text-right">
                {row.count}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <p className="text-text-secondary mt-5 max-w-3xl text-base leading-relaxed">
        <span className="text-text-primary font-medium">
          {frontierCount} executions
        </span>{" "}
        have a persisted frontier verdict. Those come from the sampler, which
        keeps about one trace in ten by trace id hash, so frontier review is a
        sample and not coverage.
      </p>
    </section>
  );
}
