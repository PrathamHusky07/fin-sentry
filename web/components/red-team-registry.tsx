"use client";

import { useState } from "react";
import {
  ModeBadge,
  RedTeamOutcomeBadge,
  SeverityBadge,
} from "@/components/red-team-badges";
import { formatUtcSeconds } from "@/lib/format";
import {
  CATEGORY_LABEL,
  expectationLabel,
  expectedLabel,
  groupByCategory,
  layerLabel,
  type ScenarioView,
} from "@/lib/red-team";

const SMALL_BUTTON =
  "border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";

function LatestResult({ scenario }: { scenario: ScenarioView }) {
  const last = scenario.last_execution;
  if (last === null) {
    return (
      <span className="text-text-tertiary border-border-strong w-fit rounded-md border border-dashed px-2 py-0.5 text-xs">
        Not run
      </span>
    );
  }
  return (
    <span className="flex flex-col gap-1 lg:items-end">
      <span className="flex flex-wrap items-center gap-2">
        <RedTeamOutcomeBadge outcome={last.outcome} state={last.state} />
        {last.outcome === "caught" ? (
          <span className="text-text-secondary text-sm">
            by {layerLabel(last.acting_layer)}
          </span>
        ) : null}
      </span>
      <span className="text-text-tertiary text-xs">
        {expectationLabel(last)}
        {last.finished_at ? `, ${formatUtcSeconds(last.finished_at)} UTC` : ""}
      </span>
    </span>
  );
}

function ScenarioDetails({ scenario }: { scenario: ScenarioView }) {
  return (
    <div className="border-border mt-4 grid gap-6 border-t pt-4 lg:grid-cols-2">
      <div className="space-y-4">
        <p className="text-text-secondary text-base leading-relaxed">
          {scenario.description}
        </p>
        <div>
          <p className="text-text-tertiary text-sm">Why this is expected</p>
          <p className="text-text-primary text-base leading-relaxed">
            {scenario.expected.rationale}
          </p>
        </div>
        <div>
          <p className="text-text-tertiary text-sm">Severity rationale</p>
          <p className="text-text-primary text-base leading-relaxed">
            {scenario.severity_rationale}
          </p>
        </div>
      </div>
      <div className="space-y-4">
        <div>
          <p className="text-text-tertiary text-sm">
            Controlled input, stored with the scenario
          </p>
          <pre className="bg-surface border-border thin-scroll mt-1 max-h-56 overflow-auto rounded-md border p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
            {JSON.stringify(scenario.input, null, 2)}
          </pre>
        </div>
        <div>
          <p className="text-text-tertiary text-sm">
            Evidence required before a catch is accepted
          </p>
          <ul className="text-text-secondary mt-1 flex flex-wrap gap-2 font-mono text-xs">
            {scenario.required_evidence.map((key) => (
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
    </div>
  );
}

/**
 * The stored scenarios by category. Each row shows what the scenario expects,
 * which is a stored hypothesis, next to the latest persisted result, which is
 * the only thing that says whether it held.
 */
export function RedTeamRegistry({
  scenarios,
  selected,
  busy,
  onToggle,
  onRunOne,
}: {
  scenarios: ScenarioView[];
  selected: Set<string>;
  busy: boolean;
  onToggle: (id: string) => void;
  onRunOne: (id: string, judgeAssisted: boolean) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [confirming, setConfirming] = useState<string | null>(null);

  function toggleOpen(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <section aria-labelledby="rt-registry-heading" className="mt-12">
      <h2 id="rt-registry-heading" className="eyebrow">
        Scenario registry
      </h2>
      <p className="text-text-secondary mt-3 max-w-3xl text-base leading-relaxed">
        {scenarios.length} versioned scenarios, each aimed at a defense that
        exists in the code. The expectation is stored with the scenario. The
        result comes only from running it.
      </p>
      {groupByCategory(scenarios).map(({ category, scenarios: group }) => (
        <div key={category} className="mt-8">
          <h3 className="text-text-primary text-lg font-semibold">
            {CATEGORY_LABEL[category]}
          </h3>
          <ul className="border-border mt-2 border-t">
            {group.map((s) => {
              const judge = s.mode === "judge_assisted";
              return (
                <li key={s.id} className="border-border border-b py-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="flex min-w-0 gap-1">
                      <label className="relative flex h-11 w-11 shrink-0 items-center justify-center">
                        <input
                          type="checkbox"
                          checked={selected.has(s.id)}
                          disabled={judge || busy}
                          onChange={() => onToggle(s.id)}
                          aria-label={
                            judge
                              ? `${s.id} runs alone and cannot be selected`
                              : `Select ${s.id}`
                          }
                          className="peer absolute inset-0 h-11 w-11 cursor-pointer opacity-0 disabled:cursor-not-allowed"
                        />
                        <span
                          aria-hidden="true"
                          className="border-border-strong peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:outline-accent h-5 w-5 rounded border peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-disabled:opacity-40"
                        />
                        <svg
                          viewBox="0 0 20 20"
                          aria-hidden="true"
                          className="text-background pointer-events-none absolute h-3.5 w-3.5 opacity-0 peer-checked:opacity-100"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3"
                        >
                          <path
                            d="M4 10.5l4 4 8-9"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </label>
                      <div className="min-w-0">
                        <p className="text-text-tertiary font-mono text-xs">
                          {s.id}, version {s.version}
                        </p>
                        <button
                          type="button"
                          aria-expanded={open.has(s.id)}
                          onClick={() => toggleOpen(s.id)}
                          className="text-text-primary hover:text-accent min-h-11 text-left text-base font-medium"
                        >
                          {s.title}
                        </button>
                        <div className="flex flex-wrap items-center gap-2">
                          <ModeBadge mode={s.mode} />
                          <SeverityBadge severity={s.severity} />
                          <span className="text-text-secondary text-sm">
                            Tests {layerLabel(s.target_layer)}
                          </span>
                        </div>
                        <p className="text-text-secondary mt-2 text-sm">
                          Expected: {expectedLabel(s.expected)}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-col gap-2 pl-12 lg:items-end lg:pl-0">
                      <LatestResult scenario={s} />
                      {judge ? (
                        confirming === s.id ? (
                          <div className="border-signal/40 bg-signal/5 max-w-sm rounded-lg border p-3">
                            <p className="text-text-primary text-sm">
                              This run sends a fixed answer and its context to
                              Gemini. It spends model calls from the project
                              credit and runs alone.
                            </p>
                            <div className="mt-2 flex gap-2">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => {
                                  setConfirming(null);
                                  onRunOne(s.id, true);
                                }}
                                className={`${SMALL_BUTTON} border-signal/60`}
                              >
                                Confirm and run
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirming(null)}
                                className={SMALL_BUTTON}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setConfirming(s.id)}
                            className={SMALL_BUTTON}
                          >
                            Run with Gemini judge
                          </button>
                        )
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => onRunOne(s.id, false)}
                          className={SMALL_BUTTON}
                        >
                          Run {s.id}
                        </button>
                      )}
                    </div>
                  </div>
                  {open.has(s.id) ? <ScenarioDetails scenario={s} /> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}
