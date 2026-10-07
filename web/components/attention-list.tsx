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
 * Attention Required as a decision surface. Each item says what the data
 * shows, why it matters, and where to go next. Severity is a left rule and a
 * word, never color alone. No item exists unless a real rule fired.
 */
export function AttentionList({ items }: { items: AttentionItem[] }) {
  return (
    <section aria-labelledby="attention-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="attention-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Attention required
        </h2>
        <p className="text-text-tertiary text-sm">
          Ordered by severity. Each item comes from a rule over persisted data.
        </p>
      </div>

      {items.length === 0 ? (
        <p className="border-border text-text-secondary mt-6 border-y py-8 text-base">
          No rule fired. Calibration is at or above recovery, no executions
          errored, the judge tiers agree, and every delivered answer has a
          verdict.
        </p>
      ) : (
        <ul className="border-border mt-6 border-t">
          {items.map((item) => (
            <li
              key={item.key}
              className="border-border relative grid gap-x-10 gap-y-4 border-b py-7 pl-5 lg:grid-cols-[1fr_1fr_15rem] lg:items-start"
            >
              <span
                aria-hidden="true"
                className={`absolute top-7 bottom-7 left-0 w-[3px] rounded-full ${TONE_BAR[item.tone]}`}
              />
              <div className="lg:col-span-3">
                <p className={`eyebrow ${TONE_TEXT[item.tone]}`}>
                  {TONE_LABEL[item.tone]}
                </p>
                <h3 className="text-text-primary mt-1.5 text-xl font-semibold tracking-tight">
                  {item.title}
                </h3>
              </div>
              <div>
                <p className="eyebrow">What happened</p>
                <p className="text-text-secondary mt-1.5 text-base leading-relaxed">
                  {item.what}
                </p>
              </div>
              <div>
                <p className="eyebrow">Why it matters</p>
                <p className="text-text-secondary mt-1.5 text-base leading-relaxed">
                  {item.why}
                </p>
              </div>
              <div className="lg:self-end lg:justify-self-end">
                <Link
                  href={item.href}
                  className="border-border-strong text-text-primary hover:bg-surface hover:border-text-tertiary inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium whitespace-nowrap transition-colors"
                >
                  {item.cta}
                  <span aria-hidden="true">→</span>
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
