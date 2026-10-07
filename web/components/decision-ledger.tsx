import { DECISIONS } from "@/lib/decisions";

const COLUMNS = [
  { key: "problem", label: "Problem" },
  { key: "decision", label: "Decision" },
  { key: "tradeoff", label: "Tradeoff" },
  { key: "consequence", label: "Consequence" },
] as const;

/**
 * The engineering decisions as a ledger: one row per decision, four
 * columns that read left to right as a short argument. Every word is
 * visible at rest. Hover or focus lights a row (its number, its rule and
 * its Decision column) so the eye can follow one argument at a time; it
 * reveals nothing, so touch and keyboard see the same content.
 */
export function DecisionLedger() {
  return (
    <div>
      <div
        aria-hidden="true"
        className="border-border bg-background/90 sticky top-[var(--nav-h)] z-10 hidden border-b backdrop-blur lg:grid lg:grid-cols-4 lg:gap-x-8 lg:pl-14"
      >
        {COLUMNS.map((column) => (
          <p key={column.key} className="text-text-tertiary py-3 text-sm">
            {column.label}
          </p>
        ))}
      </div>

      <ol>
        {DECISIONS.map((decision, i) => (
          <li
            key={decision.title}
            tabIndex={0}
            className="group border-border hover:bg-surface/50 focus-visible:bg-surface/50 relative border-b py-8 pl-0 transition-colors lg:pl-14"
          >
            <span
              aria-hidden="true"
              className="bg-accent absolute top-8 bottom-8 left-0 hidden w-0.5 origin-top scale-y-0 rounded-full transition-transform duration-300 group-hover:scale-y-100 group-focus-visible:scale-y-100 lg:block"
            />
            <div className="flex items-baseline gap-4">
              <span
                aria-hidden="true"
                className="text-text-tertiary group-hover:text-accent group-focus-visible:text-accent absolute top-8 left-3 hidden font-mono text-sm tabular-nums transition-colors lg:block"
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="text-text-primary text-xl font-semibold tracking-tight text-balance">
                {decision.title}
              </h3>
            </div>
            <dl className="mt-5 grid gap-x-8 gap-y-5 lg:grid-cols-4">
              {COLUMNS.map((column) => (
                <div key={column.key}>
                  <dt className="text-text-tertiary text-sm lg:sr-only">
                    {column.label}
                  </dt>
                  <dd
                    className={`mt-1 text-[15px] leading-relaxed transition-colors lg:mt-0 ${
                      column.key === "decision"
                        ? "text-text-primary"
                        : "text-text-secondary group-hover:text-text-primary group-focus-visible:text-text-primary"
                    }`}
                  >
                    {decision[column.key]}
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ol>
    </div>
  );
}
