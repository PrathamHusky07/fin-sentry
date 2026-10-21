"use client";

import {
  ExpectationChip,
  OutcomeGlyph,
  RedTeamOutcomeBadge,
  SeverityBadge,
  differenceText,
  type GlyphKind,
} from "@/components/red-team-badges";
import { InvestigateThis } from "@/components/red-team-investigate";
import type { Summary } from "@/lib/incidents";
import {
  ATTENTION_LABEL,
  CHANGE_LABEL,
  OUTCOMES,
  OUTCOME_LABEL,
  OUTCOME_MEANING,
  SAFETY_BOUND_MEANING,
  canInvestigate,
  expectedLabel,
  findingHeadline,
  isSafetyBoundSkip,
  type AttentionItem,
  type AttentionKind,
  type LatestSummary,
  type Outcome,
} from "@/lib/red-team";

const KIND_TONE: Record<AttentionKind, string> = {
  regression: "var(--failure)",
  missed: "var(--failure)",
  differs: "var(--warning)",
  lost_result: "var(--failure)",
  known_gap: "var(--warning)",
  unavailable: "var(--warning)",
  failed: "var(--failure)",
  skipped: "var(--text-tertiary)",
  inconclusive: "var(--text-tertiary)",
};

const SEGMENT: Record<Outcome, string> = {
  caught: "bg-positive/70",
  missed: "bg-failure",
  evaluator_unavailable: "bg-warning/60",
  execution_failed: "bg-failure/50",
  inconclusive: "bg-text-tertiary/60",
};

const TEXT_TONE: Record<Outcome, string> = {
  caught: "text-positive",
  missed: "text-failure",
  evaluator_unavailable: "text-warning",
  execution_failed: "text-failure",
  inconclusive: "text-text-secondary",
};

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function AttentionCard({
  item,
  sessions,
  onOpenScenario,
  onOpenEvidence,
  onStarted,
}: {
  item: AttentionItem;
  sessions: Summary[] | null;
  onOpenScenario: (id: string) => void;
  onOpenEvidence: (id: string) => void;
  onStarted: () => void;
}) {
  const { scenario: s, execution: e, kind, change } = item;
  const diff = differenceText(e);
  return (
    <li
      className="border-border bg-background-elevated/60 relative rounded-xl border p-4 pl-5 sm:p-5 sm:pl-6"
      style={{ ["--tone" as string]: KIND_TONE[kind] }}
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-3 left-0 w-1 rounded-r"
        style={{ background: "var(--tone)" }}
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-text-primary text-lg font-semibold tracking-tight">
          {ATTENTION_LABEL[kind]}
        </p>
        <SeverityBadge severity={s.severity} />
      </div>
      <p className="text-text-secondary mt-1 font-mono text-base sm:text-sm">
        {s.id}, version {e.scenario_version}
      </p>
      <p className="text-text-primary mt-1 text-lg">{s.title}</p>
      {change ? (
        <p className="text-text-secondary mt-1 text-base">
          {CHANGE_LABEL[change]}, from the stored history.
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="border-border rounded-lg border border-dashed p-3">
          <p className="text-text-tertiary text-base sm:text-sm">
            Expected, stored with the scenario
          </p>
          <p className="text-text-primary mt-1 text-base font-medium">
            {expectedLabel(e.expected)}
          </p>
          <p className="text-text-secondary mt-1 text-base leading-snug sm:text-sm">
            {e.expected.rationale}
          </p>
        </div>
        <div className="border-border rounded-lg border p-3">
          <p className="text-text-tertiary text-base sm:text-sm">
            Observed, from the latest execution
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <RedTeamOutcomeBadge
              outcome={e.outcome}
              state={e.state}
              safetyBound={isSafetyBoundSkip(e)}
            />
            <ExpectationChip e={e} />
          </div>
          <p className="text-text-secondary mt-2 text-base leading-snug sm:text-sm">
            {diff ?? e.reason}
          </p>
          {e.outcome === "caught" ? null : (
            <p className="text-text-tertiary mt-1 text-base sm:text-sm">
              Acting layer: none credited.
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-start gap-3">
        <button
          type="button"
          onClick={() => onOpenScenario(s.id)}
          className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-base font-medium sm:text-sm"
        >
          Open the scenario
        </button>
        <button
          type="button"
          onClick={() => onOpenEvidence(e.execution_id)}
          aria-label={`Open evidence for ${s.id}, run ${e.run_id.slice(0, 8)}`}
          className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-base font-medium sm:text-sm"
        >
          Open the evidence
        </button>
        {canInvestigate(e) ? (
          <InvestigateThis
            execution={e}
            sessions={sessions}
            onStarted={onStarted}
          />
        ) : null}
      </div>
    </li>
  );
}

/** One bar for the registry: a segment per latest outcome, sized by how many scenarios have
 * it. It carries no number a reader cannot recount from the rows below, and a state with no
 * scenario has no segment. */
function OutcomeBar({
  summary,
  persistence,
}: {
  summary: LatestSummary;
  persistence: boolean;
}) {
  if (!persistence || summary.scenarioCount === 0) return null;
  const segments = [
    ...OUTCOMES.filter((o) => summary.counts[o] > 0).map((o) => ({
      key: o,
      n: summary.counts[o],
      cls: SEGMENT[o],
      label: `${summary.counts[o]} ${OUTCOME_LABEL[o].toLowerCase()}`,
    })),
    ...(summary.notRun > 0
      ? [
          {
            key: "not_run",
            n: summary.notRun,
            cls: "border border-dashed border-border-strong",
            label: `${summary.notRun} not run`,
          },
        ]
      : []),
  ];
  const label = `Latest result of ${plural(summary.scenarioCount, "scenario", "scenarios")}: ${segments.map((s) => s.label).join(", ")}.`;
  return (
    <div>
      <div
        role="img"
        aria-label={label}
        className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full"
      >
        {segments.map((seg) => (
          <span
            key={seg.key}
            className={`${seg.cls} first:rounded-l-full last:rounded-r-full`}
            style={{ flexGrow: seg.n, flexBasis: 0 }}
          />
        ))}
      </div>
      <p className="text-text-secondary mt-2 text-base sm:text-sm">
        {segments.map((s) => s.label).join(", ")}.
      </p>
    </div>
  );
}

/**
 * The five outcomes as a key with the counts that exist. A state nobody has recorded says so
 * in words and does not draw a zero, so three empty states never carry the weight of the one
 * real finding above. Scenario counts are the latest result per scenario. Execution counts
 * cover every stored execution that was loaded.
 */
function OutcomeKey({
  summary,
  executionCounts,
  persistence,
}: {
  summary: LatestSummary;
  executionCounts: Record<Outcome, number> | null;
  persistence: boolean;
}) {
  return (
    <dl className="divide-border border-border divide-y rounded-xl border">
      {OUTCOMES.map((o) => {
        const scenarios = summary.counts[o];
        const executions = executionCounts?.[o] ?? null;
        const none = persistence && scenarios === 0 && (executions ?? 0) === 0;
        const kind: GlyphKind = o;
        return (
          <div
            key={o}
            data-outcome={o}
            data-recorded={none ? "false" : "true"}
            className={`grid gap-1 p-4 sm:grid-cols-[13rem_1fr_11rem] sm:items-start sm:gap-4 ${none ? "opacity-75" : ""}`}
          >
            <dt
              className={`flex items-center gap-2 text-base font-medium ${none ? "text-text-secondary" : TEXT_TONE[o]}`}
            >
              <OutcomeGlyph kind={kind} className="h-5 w-5" />
              {OUTCOME_LABEL[o]}
            </dt>
            <dd
              className={`text-text-secondary text-base leading-snug sm:text-sm ${none ? "hidden sm:block" : ""}`}
            >
              {OUTCOME_MEANING[o]}
              {o === "execution_failed" && summary.safetyBoundSkips > 0
                ? ` ${plural(summary.safetyBoundSkips, "of the latest results was", "of the latest results were")} not run (safety bound). ${SAFETY_BOUND_MEANING}`
                : ""}
            </dd>
            <dd className="text-text-primary text-base sm:text-right sm:text-sm">
              {!persistence
                ? "Unknown"
                : none
                  ? "None recorded"
                  : `${plural(scenarios, "scenario", "scenarios")}${executions === null ? "" : `, ${plural(executions, "execution", "executions")}`}`}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/**
 * The first thing on the page: what needs attention, ranked, then the outcome key. The
 * headline is derived from the stored results and never says nothing is wrong when results
 * do not exist.
 */
export function RedTeamAttention({
  summary,
  items,
  executionCounts,
  persistence,
  sessions,
  onOpenScenario,
  onOpenEvidence,
  onStarted,
}: {
  summary: LatestSummary;
  items: AttentionItem[];
  executionCounts: Record<Outcome, number> | null;
  persistence: boolean;
  sessions: Summary[] | null;
  onOpenScenario: (id: string) => void;
  onOpenEvidence: (id: string) => void;
  onStarted: () => void;
}) {
  return (
    <div>
      {persistence ? (
        <p className="text-text-primary max-w-3xl text-xl leading-snug font-medium text-pretty sm:text-2xl">
          {findingHeadline(summary, items)}
        </p>
      ) : (
        <p
          role="alert"
          className="border-warning/40 bg-warning/10 text-text-primary max-w-3xl rounded-lg border p-4 text-base"
        >
          The result store could not be read. The counts below are unknown, not
          zero.
        </p>
      )}

      {persistence && items.length > 0 ? (
        <ul
          className="mt-6 space-y-4"
          aria-label="Scenarios that need attention"
        >
          {items.map((item) => (
            <AttentionCard
              key={item.scenario.id}
              item={item}
              sessions={sessions}
              onOpenScenario={onOpenScenario}
              onOpenEvidence={onOpenEvidence}
              onStarted={onStarted}
            />
          ))}
        </ul>
      ) : null}

      <div className="mt-8">
        <OutcomeBar summary={summary} persistence={persistence} />
      </div>
      <div className="mt-5">
        <OutcomeKey
          summary={summary}
          executionCounts={executionCounts}
          persistence={persistence}
        />
        <p className="text-text-tertiary mt-3 text-base sm:text-sm">
          Scenario counts use the most recent stored execution of each scenario.
          Execution counts cover every stored execution that was loaded. Only a
          caught result means a defense acted, and the layer is named on it.
        </p>
      </div>
    </div>
  );
}
