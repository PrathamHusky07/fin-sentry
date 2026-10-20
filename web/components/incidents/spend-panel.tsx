import { budgetRows, spendNote, type Detail } from "@/lib/incidents";

function Bar({ used, max }: { used: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (used / max) * 100) : 0;
  return (
    <div
      className="bg-surface h-1.5 w-full overflow-hidden rounded-full"
      role="presentation"
    >
      <div
        className="h-full rounded-full"
        style={{
          width: `${pct}%`,
          background: pct >= 100 ? "var(--warning)" : "var(--accent)",
        }}
      />
    </div>
  );
}

/** What the investigation was allowed and what it used, from the stored budgets and counts,
 * and what the model calls cost. Cost is counted from the provider's usage metadata at the
 * platform's published rates, so it is an estimate and is labelled as one. */
export function SpendPanel({ detail: d }: { detail: Detail }) {
  const usage = d.usage;
  return (
    <section
      id="budget"
      aria-labelledby="budget-heading"
      className="scroll-mt-32"
    >
      <h2
        id="budget-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Budget and spend
      </h2>
      {!usage ? (
        <p className="border-border-strong text-text-secondary mt-4 max-w-3xl rounded-xl border border-dashed px-5 py-8 text-base leading-relaxed">
          No usage was stored for this session. A session that ends without a
          report or a final state cannot say what it used.
        </p>
      ) : (
        <div className="mt-6 grid gap-10 lg:grid-cols-2">
          <div>
            <h3 className="text-text-primary text-lg font-semibold">
              Ceilings and use
            </h3>
            <p className="text-text-tertiary mt-0.5 text-sm">
              Starting values that bound one investigation, not tuned optima.
            </p>
            <ul className="mt-4 space-y-4">
              {budgetRows(usage, d.origin).map((r) => (
                <li key={r.label}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-text-primary text-base">
                      {r.label}
                    </span>
                    <span className="tabular-metric text-text-secondary text-base">
                      {r.used}
                      {r.unit} of {r.max}
                      {r.unit}
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <Bar used={r.used} max={r.max} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-text-primary text-lg font-semibold">
              Model spend
            </h3>
            <dl className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <dt className="text-text-tertiary text-sm">Model calls</dt>
                <dd className="tabular-metric text-text-primary text-2xl">
                  {usage.model.calls}
                </dd>
              </div>
              <div>
                <dt className="text-text-tertiary text-sm">Estimated cost</dt>
                <dd className="tabular-metric text-text-primary text-2xl">
                  ${usage.model.cost_usd.toFixed(4)}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-text-tertiary text-sm">Tokens</dt>
                <dd className="tabular-metric text-text-secondary text-base">
                  {usage.model.prompt_tokens.toLocaleString("en-US")} input,{" "}
                  {usage.model.candidates_tokens.toLocaleString("en-US")}{" "}
                  output, {usage.model.thought_tokens.toLocaleString("en-US")}{" "}
                  thinking
                </dd>
              </div>
            </dl>
            <p className="text-text-secondary mt-3 text-base leading-relaxed">
              {spendNote(usage, d.origin)}
            </p>
            {usage.model.call_log.length > 0 ? (
              <table className="mt-4 w-full text-left text-sm">
                <caption className="sr-only">
                  Each planner call, how long it took and how it ended.
                </caption>
                <thead className="text-text-tertiary">
                  <tr className="border-border border-b">
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Round
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Outcome
                    </th>
                    <th scope="col" className="py-2 pr-3 font-normal">
                      Seconds
                    </th>
                    <th scope="col" className="py-2 font-normal">
                      Cost
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {usage.model.call_log.map((c, i) => (
                    <tr key={i} className="border-border border-b">
                      <td className="tabular-metric py-2 pr-3">{c.round}</td>
                      <td className="py-2 pr-3">
                        {c.outcome === "ok"
                          ? "Returned a plan"
                          : `Failed: ${c.error_class ?? "unknown"}`}
                      </td>
                      <td className="tabular-metric py-2 pr-3">
                        {c.elapsed_s.toFixed(2)}
                      </td>
                      <td className="tabular-metric py-2">
                        ${c.cost_usd.toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
