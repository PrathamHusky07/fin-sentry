import {
  QUERY_OUTCOME_LABEL,
  QUERY_OUTCOME_MEANING,
  type QueryOutcome,
} from "@/lib/incidents";

const STATES: { key: QueryOutcome; border: string }[] = [
  { key: "returned", border: "border-border-strong" },
  { key: "verified_empty", border: "border-border-strong" },
  { key: "unverified_empty", border: "border-dashed border-warning/60" },
  { key: "unavailable", border: "border-dashed border-failure/50" },
  { key: "rejected", border: "border-dashed border-border-strong" },
];

/** A compact key to what a case file can say. The wording of the five query states is the
 * same constant the case file renders, so this key cannot drift from it. */
export function AgentGuide() {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-16">
      <div>
        <h2
          id="guide-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight text-balance"
        >
          Reading a case file
        </h2>
        <p className="text-text-secondary mt-3 text-base leading-relaxed text-pretty">
          A solid border says something about the platform. A dashed border says
          nothing about it. The same rule holds for the states below.
        </p>
      </div>
      <div className="space-y-8">
        <div>
          <h3 className="eyebrow">What a query result can mean</h3>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {STATES.map(({ key, border }) => (
              <li
                key={key}
                className={`rounded-lg border p-4 ${border} bg-background-elevated/50`}
              >
                <p className="text-text-primary text-base font-medium">
                  {QUERY_OUTCOME_LABEL[key]}
                </p>
                <p className="text-text-secondary mt-1 text-base leading-snug">
                  {QUERY_OUTCOME_MEANING[key]}
                </p>
              </li>
            ))}
          </ul>
        </div>
        <dl className="grid gap-6 sm:grid-cols-2">
          <div>
            <dt className="text-text-primary text-base font-medium">
              Best-supported hypothesis
            </dt>
            <dd className="text-text-secondary mt-1 text-base leading-relaxed">
              The records are consistent with it and no rival is also supported.
              That is not a proven cause, and the case file says so on the
              result.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-base font-medium">
              Abstained
            </dt>
            <dd className="text-text-secondary mt-1 text-base leading-relaxed">
              The investigation finished and found no supported cause, or could
              not read the source it needed. It is stored and shown as a
              complete result, not as an error.
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
