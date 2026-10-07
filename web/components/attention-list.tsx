import Link from "next/link";
import type { AttentionItem, AttentionTone } from "@/lib/attention";

const TONE_BAR: Record<AttentionTone, string> = {
  failure: "bg-failure",
  disagreement: "bg-disagreement",
  warning: "bg-warning",
  info: "bg-info",
};

const TONE_LABEL: Record<AttentionTone, string> = {
  failure: "Failing",
  disagreement: "Judges disagree",
  warning: "Degraded",
  info: "Worth a look",
};

const TONE_TEXT: Record<AttentionTone, string> = {
  failure: "text-failure",
  disagreement: "text-disagreement",
  warning: "text-warning",
  info: "text-info",
};

/**
 * Attention as ranked signals. Each row leads with its figure, the one
 * number that makes the case, then the plain-language title, what it means
 * and why it matters. The technical reading sits last, for the engineer who
 * wants it. Severity is a spine, a word and the order, never color alone.
 * No signal exists unless a rule over persisted data fired.
 */
export function AttentionList({ items }: { items: AttentionItem[] }) {
  return (
    <section aria-labelledby="attention-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="attention-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Signals, most severe first
        </h2>
        <p className="text-text-tertiary text-sm">
          Each one comes from a rule over persisted data.
        </p>
      </div>

      {items.length === 0 ? (
        <p className="border-border text-text-secondary mt-6 border-y py-8 text-base">
          No rule fired over the persisted executions. None errored, the judge
          tiers agree, and every delivered answer has a verdict.
        </p>
      ) : (
        <ol className="border-border mt-6 border-t">
          {items.map((item, i) => (
            <li key={item.key} className="border-border border-b">
              <Link
                href={item.href}
                className="group hover:bg-surface/50 relative grid gap-x-10 gap-y-3 py-7 pl-6 transition-colors lg:grid-cols-[13rem_1fr_auto] lg:items-center"
              >
                <span
                  aria-hidden="true"
                  className={`absolute top-6 bottom-6 left-0 w-[3px] rounded-full transition-all group-hover:top-4 group-hover:bottom-4 ${TONE_BAR[item.tone]}`}
                />
                <div>
                  <p className="tabular-metric text-text-primary text-3xl leading-none font-semibold tracking-tight">
                    {item.figure}
                  </p>
                  <p className="text-text-secondary mt-2 text-sm">
                    {item.figureNote}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${TONE_TEXT[item.tone]}`}>
                    {TONE_LABEL[item.tone]}
                    <span className="text-text-tertiary font-normal">
                      , signal {i + 1} of {items.length}
                    </span>
                  </p>
                  <h3 className="text-text-primary mt-1 text-xl font-semibold tracking-tight text-balance">
                    {item.title}
                  </h3>
                  <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
                    {item.what} {item.why}
                  </p>
                  {item.detail ? (
                    <p className="text-text-tertiary mt-2 max-w-2xl font-mono text-xs leading-relaxed">
                      {item.detail}
                    </p>
                  ) : null}
                </div>
                <span className="text-text-primary inline-flex min-h-11 items-center gap-2 text-sm font-medium whitespace-nowrap">
                  {item.cta}
                  <span
                    aria-hidden="true"
                    className="transition-transform group-hover:translate-x-1"
                  >
                    →
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
