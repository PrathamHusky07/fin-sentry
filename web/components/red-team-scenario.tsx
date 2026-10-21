"use client";

import Link from "next/link";
import { useId, useState } from "react";
import {
  ExpectationChip,
  ModeBadge,
  RedTeamOutcomeBadge,
  SeverityBadge,
  differenceText,
} from "@/components/red-team-badges";
import { RedTeamHistory } from "@/components/red-team-history";
import { InvestigateThis } from "@/components/red-team-investigate";
import { formatUtcSeconds } from "@/lib/format";
import type { Summary } from "@/lib/incidents";
import {
  CATEGORY_LABEL,
  OUTCOME_MEANING,
  SAFETY_BOUND_MEANING,
  canInvestigate,
  expectedLabel,
  formatCost,
  isSafetyBoundSkip,
  layerLabel,
  stageOf,
  STAGE_LABEL,
  traceHref,
  type ExecutionRecord,
  type ScenarioView,
} from "@/lib/red-team";

const BUTTON =
  "min-h-11 rounded-lg border px-4 text-base font-medium sm:text-sm disabled:cursor-not-allowed disabled:opacity-50";

function Facts({ evidence }: { evidence: Record<string, unknown> }) {
  const scalar = Object.entries(evidence).filter(
    ([, v]) => v === null || typeof v !== "object",
  );
  if (scalar.length === 0) return null;
  return (
    <dl className="mt-3 flex flex-wrap gap-2">
      {scalar.map(([k, v]) => (
        <div
          key={k}
          className="border-border-strong flex min-h-8 items-center gap-2 rounded border px-2 font-mono text-base sm:text-xs"
        >
          <dt className="text-text-tertiary">{k}</dt>
          <dd className="text-text-primary break-all">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function LatestResult({ e }: { e: ExecutionRecord }) {
  const diff = differenceText(e);
  const skipped = isSafetyBoundSkip(e);
  return (
    <section
      aria-label="Latest result"
      className="border-border rounded-lg border p-4"
    >
      <p className="text-text-tertiary text-base sm:text-sm">
        Latest result, recorded{" "}
        {e.finished_at
          ? `${formatUtcSeconds(e.finished_at)} UTC`
          : "not yet finished"}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <RedTeamOutcomeBadge
          outcome={e.outcome}
          state={e.state}
          safetyBound={skipped}
        />
        <ExpectationChip e={e} />
      </div>
      {diff ? (
        <p className="text-warning mt-2 text-base leading-snug">{diff}</p>
      ) : null}
      {e.reason ? (
        <p className="text-text-secondary mt-2 text-base leading-relaxed">
          {e.reason}
        </p>
      ) : null}
      <p className="text-text-tertiary mt-2 text-base leading-snug sm:text-sm">
        {e.outcome
          ? skipped
            ? SAFETY_BOUND_MEANING
            : OUTCOME_MEANING[e.outcome]
          : "Not finished yet."}
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="border-border rounded-lg border border-dashed p-3">
          <p className="text-text-tertiary text-base sm:text-sm">
            Expected, stored with version {e.scenario_version}
          </p>
          <p className="text-text-primary mt-1 text-base font-medium">
            {expectedLabel(e.expected)}
          </p>
        </div>
        <div className="border-border rounded-lg border p-3">
          <p className="text-text-tertiary text-base sm:text-sm">
            Which defense acted
          </p>
          <p className="text-text-primary mt-1 text-base font-medium">
            {e.outcome === "caught"
              ? layerLabel(e.acting_layer)
              : "None credited"}
          </p>
          {e.acting_check ? (
            <p className="text-text-secondary text-base sm:text-sm">
              {e.acting_check}
            </p>
          ) : null}
        </div>
      </div>
      <Facts evidence={e.evidence} />
      <p className="text-text-tertiary mt-3 text-base sm:text-sm">
        A recorded execution of the real defense on the scenario’s controlled
        input. It is stored, not a fixture, and it is not a measure of how often
        a real attacker would succeed.
      </p>
      {e.trace_ref ? (
        <Link
          href={traceHref(e.trace_ref)}
          className="text-accent mt-1 inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
        >
          Open the trace in Investigations
        </Link>
      ) : null}
    </section>
  );
}

function Definition({ scenario: s }: { scenario: ScenarioView }) {
  return (
    <div className="border-border-strong space-y-4 rounded-lg border border-dashed p-4">
      <p className="text-text-tertiary text-base sm:text-sm">
        The definition, stored with version {s.version}. It states what the
        scenario plans to show. It is not a result.
      </p>
      <p className="text-text-secondary text-base leading-relaxed">
        {s.description}
      </p>
      <div>
        <p className="text-text-tertiary text-base sm:text-sm">
          Why this is expected
        </p>
        <p className="text-text-primary text-base leading-relaxed">
          {s.expected.rationale}
        </p>
      </div>
      <div>
        <p className="text-text-tertiary text-base sm:text-sm">
          Severity rationale
        </p>
        <p className="text-text-primary text-base leading-relaxed">
          {s.severity_rationale}
        </p>
      </div>
      <div>
        <p className="text-text-tertiary text-base sm:text-sm">
          Controlled input, stored with the scenario
        </p>
        <pre className="bg-surface border-border thin-scroll mt-1 max-h-56 overflow-auto rounded-md border p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
          {JSON.stringify(s.input, null, 2)}
        </pre>
      </div>
      <div>
        <p className="text-text-tertiary text-base sm:text-sm">
          Evidence required before a catch is accepted
        </p>
        <ul className="text-text-secondary mt-1 flex flex-wrap gap-2 font-mono text-base sm:text-xs">
          {s.required_evidence.map((key) => (
            <li
              key={key}
              className="border-border-strong rounded border px-1.5 py-0.5"
            >
              {key}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * One scenario, summary first. The latest result and its actions come before anything else.
 * The recorded executions and the stored definition sit behind two tabs, so a result and the
 * plan it was judged against are never read as the same thing.
 */
export function RedTeamScenario({
  scenario: s,
  history,
  sessions,
  busy,
  persistence,
  onRunOne,
  onOpenEvidence,
  onStarted,
}: {
  scenario: ScenarioView;
  /** Oldest first. */
  history: ExecutionRecord[];
  sessions: Summary[] | null;
  busy: boolean;
  persistence: boolean;
  onRunOne: (id: string, judgeAssisted: boolean) => void;
  onOpenEvidence: (executionId: string) => void;
  onStarted: () => void;
}) {
  const [tab, setTab] = useState<"executions" | "definition">("executions");
  const [confirming, setConfirming] = useState(false);
  const tabsId = useId();
  const last = s.last_execution;
  const judge = s.mode === "judge_assisted";
  const stage = stageOf(s.target_layer);
  const disabled = busy || !persistence;

  return (
    <article aria-label={`${s.id} ${s.title}`} className="space-y-5">
      <header>
        <p className="text-text-tertiary font-mono text-base sm:text-sm">
          {s.id}, version {s.version}
        </p>
        <h3 className="text-text-primary mt-1 text-xl font-semibold tracking-tight text-balance">
          {s.title}
        </h3>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={s.severity} />
          <ModeBadge mode={s.mode} />
          <span className="text-text-secondary text-base sm:text-sm">
            Tests {layerLabel(s.target_layer)}
            {stage ? `, ${STAGE_LABEL[stage].toLowerCase()}` : ""}.{" "}
            {CATEGORY_LABEL[s.category]}.
          </span>
        </div>
      </header>

      {last ? (
        <LatestResult e={last} />
      ) : (
        <p className="border-border-strong text-text-secondary rounded-lg border border-dashed p-4 text-base">
          This scenario has not been run, so there is no result to read.
        </p>
      )}

      <div className="flex flex-wrap items-start gap-3">
        {last ? (
          <button
            type="button"
            onClick={() => onOpenEvidence(last.execution_id)}
            aria-label={`Open evidence for ${s.id}, run ${last.run_id.slice(0, 8)}`}
            className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
          >
            Open the full evidence
          </button>
        ) : null}
        {judge ? (
          confirming ? (
            <div className="border-signal/40 bg-signal/5 max-w-md rounded-lg border p-3">
              <p className="text-text-primary text-base leading-snug">
                This run sends a fixed answer and its context to Gemini. It
                spends model calls from the project credit and runs alone.
                {last
                  ? ` The latest stored run made ${last.gemini_calls} ${last.gemini_calls === 1 ? "call" : "calls"} at a recorded ${formatCost(last.cost_usd)}.`
                  : " No earlier run is stored, so its cost is not known yet."}
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    setConfirming(false);
                    onRunOne(s.id, true);
                  }}
                  className={`${BUTTON} border-signal/60 text-text-primary hover:bg-signal/10`}
                >
                  Confirm and run
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              disabled={disabled}
              onClick={() => setConfirming(true)}
              className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
            >
              Run with Gemini judge
            </button>
          )
        ) : (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onRunOne(s.id, false)}
            className={`${BUTTON} border-accent/60 bg-accent/10 text-text-primary hover:bg-accent/20`}
          >
            Run {s.id}
          </button>
        )}
        {last && canInvestigate(last) ? (
          <InvestigateThis
            execution={last}
            sessions={sessions}
            onStarted={onStarted}
          />
        ) : null}
      </div>
      {judge ? (
        <p className="text-text-tertiary text-base sm:text-sm">
          Judge-assisted. Detection depends on the Gemini faithfulness judge, so
          a run spends model calls, and it never runs as part of a group.
        </p>
      ) : null}

      <div>
        <div
          role="tablist"
          aria-label="Scenario sections"
          className="border-border flex gap-1 border-b"
        >
          {(
            [
              ["executions", `Recorded executions (${history.length})`],
              ["definition", "Definition"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`${tabsId}-${id}-tab`}
              aria-selected={tab === id}
              aria-controls={`${tabsId}-${id}`}
              onClick={() => setTab(id)}
              className={`min-h-11 px-3 text-base transition-colors sm:text-sm ${tab === id ? "border-accent text-text-primary -mb-px border-b-2 font-medium" : "text-text-secondary hover:text-text-primary"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id={`${tabsId}-${tab}`}
          aria-labelledby={`${tabsId}-${tab}-tab`}
          className="pt-4"
        >
          {tab === "executions" ? (
            <RedTeamHistory executions={history} onOpen={onOpenEvidence} />
          ) : (
            <Definition scenario={s} />
          )}
        </div>
      </div>
    </article>
  );
}
