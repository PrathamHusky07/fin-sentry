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

/** A static key to what an investigation page can say. The wording of the five query states is
 * the same constant the detail page renders, so this key cannot drift from it. */
export function AgentGuide() {
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,22rem)_1fr] lg:gap-16">
      <div>
        <h2
          id="guide-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight text-balance"
        >
          How to read an investigation
        </h2>
        <p className="text-text-secondary mt-3 text-base leading-relaxed text-pretty">
          The agent can be wrong, and the page is built so that a wrong answer
          is visible. A solid border says something about the platform. A dashed
          border says nothing about it.
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
              That is not a proven cause, and the page says so on the result.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-base font-medium">
              Abstained
            </dt>
            <dd className="text-text-secondary mt-1 text-base leading-relaxed">
              A finished investigation that found no supported cause, or could
              not read the source it needed. It is stored and shown as a
              complete result, not as an error.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-base font-medium">
              Live platform
            </dt>
            <dd className="text-text-secondary mt-1 text-base leading-relaxed">
              Read from the running platform through the nine read-only tools,
              with a real model call. Its cost is stored with the session.
            </dd>
          </div>
          <div>
            <dt className="text-text-primary text-base font-medium">
              Fixture replay
            </dt>
            <dd className="text-text-secondary mt-1 text-base leading-relaxed">
              A known-answer case world replayed through the same code with a
              scripted planner. No model was called, and it says nothing about
              the live platform.
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
