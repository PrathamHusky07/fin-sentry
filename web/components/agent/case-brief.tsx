import Link from "next/link";
import {
  OriginBadge,
  OutcomeBadge,
  StatusBadge,
  SubsystemChip,
} from "@/components/incidents/badges";
import { formatUtc, relativeTime } from "@/lib/format";
import {
  STOPPING_LABEL,
  STOPPING_MEANING,
  TRIGGER_LABEL,
  windowMinutes,
  type Summary,
} from "@/lib/incidents";

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-text-tertiary text-base sm:text-sm">{label}</dt>
      <dd className="text-text-primary mt-0.5 text-base break-words">
        {children}
      </dd>
    </div>
  );
}

function scope(s: Summary): string {
  const parts = [
    s.scope.endpoint ? `endpoint ${s.scope.endpoint}` : null,
    s.scope.ticker ? `ticker ${s.scope.ticker}` : null,
  ].filter((p): p is string => p !== null);
  return parts.length > 0 ? parts.join(", ") : "The whole platform";
}

/** What the session concluded, from its listing fields only. A failed or interrupted session
 * shows no conclusion, and an abstention is stated as a complete result. */
function Finding({ s }: { s: Summary }) {
  if (s.status === "failed") {
    return (
      <>
        <p className="text-failure text-lg leading-snug font-medium">
          The investigator raised an error.
        </p>
        <p className="text-text-secondary mt-1 text-base">
          No conclusion was reached, so none is shown. The case file keeps what
          it ran before the error.
        </p>
      </>
    );
  }
  if (s.status === "interrupted") {
    return (
      <>
        <p className="text-warning text-lg leading-snug font-medium">
          Stopped before it finished.
        </p>
        <p className="text-text-secondary mt-1 text-base">
          The process running it ended and it was not resumed. Nothing here is a
          conclusion.
        </p>
      </>
    );
  }
  if (s.status === "running") {
    return (
      <p className="text-text-primary text-lg leading-snug font-medium">
        Still working. The case file shows what has been stored so far.
      </p>
    );
  }
  if (s.leading) {
    return (
      <>
        <div className="flex flex-wrap items-center gap-2">
          <SubsystemChip subsystem={s.leading.subsystem} />
          <span className="text-text-secondary text-base sm:text-sm">
            {s.leading.confidence} confidence, not proven
          </span>
        </div>
        <p className="text-text-primary mt-2 text-lg leading-snug text-pretty">
          {s.leading.statement}
        </p>
      </>
    );
  }
  return (
    <>
      <p className="text-text-primary text-lg leading-snug font-medium">
        No root cause was established.
      </p>
      <p className="text-text-secondary mt-1 text-base">
        The investigator abstained. That is a complete result, and the case file
        says what the records could not show.
      </p>
    </>
  );
}

/**
 * The first layer of a case, from the listing fields only: the incident, its window, the
 * outcome and why it stopped. Nothing here needs the full session, so selecting a row costs no
 * extra request. The case file opened from here holds the hypotheses and the evidence.
 */
export function CaseBrief({ summary: s }: { summary: Summary }) {
  const minutes = windowMinutes(s.window);
  const queries =
    s.queries === null
      ? "Queries not stored"
      : `${s.queries} ${s.queries === 1 ? "query" : "queries"}`;
  const model =
    s.model_calls === null
      ? "model use not stored"
      : s.model_calls === 0
        ? "no model call"
        : `${s.model_calls} model ${s.model_calls === 1 ? "call" : "calls"}, $${(s.cost_usd ?? 0).toFixed(4)}`;
  return (
    <article
      aria-label={`${TRIGGER_LABEL[s.trigger.kind]}, case summary`}
      className="space-y-5"
    >
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={s.status} />
          <OutcomeBadge outcome={s.outcome} />
          <OriginBadge origin={s.origin} planner={s.planner} />
        </div>
        <h3 className="text-text-primary mt-3 text-xl font-semibold tracking-tight text-balance">
          {TRIGGER_LABEL[s.trigger.kind]}
        </h3>
        <p className="text-text-secondary mt-1 text-base leading-relaxed text-pretty">
          {s.trigger.description}
        </p>
      </header>

      <section aria-label="Finding" className="border-border border-t pt-4">
        <Finding s={s} />
        {s.stopping_reason ? (
          <p className="text-text-secondary mt-3 text-base leading-relaxed">
            <span className="text-text-primary font-medium">
              Stopped: {STOPPING_LABEL[s.stopping_reason]}.
            </span>{" "}
            {STOPPING_MEANING[s.stopping_reason]}
          </p>
        ) : null}
      </section>

      <dl className="border-border grid gap-x-6 gap-y-4 border-t pt-4 sm:grid-cols-2">
        <Fact label="Scope">{scope(s)}</Fact>
        <Fact label="Time window">
          {formatUtc(s.window.start)} to {formatUtc(s.window.end)}
          <span className="text-text-secondary block text-base sm:text-sm">
            {minutes} {minutes === 1 ? "minute" : "minutes"}
          </span>
        </Fact>
        <Fact label="Work done">
          {queries}, {model}
        </Fact>
        <Fact label="Started">
          <span title={s.created_at}>{relativeTime(s.created_at)}</span>
        </Fact>
      </dl>

      <Link
        href={`/agent/${s.investigation_id}`}
        className="border-accent/60 bg-accent/10 text-text-primary hover:bg-accent/20 inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-base font-medium transition-colors sm:text-sm"
      >
        Open the case file
        <span aria-hidden="true">→</span>
      </Link>
    </article>
  );
}
