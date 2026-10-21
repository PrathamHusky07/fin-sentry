"use client";

import { useState } from "react";

type Actor = "trigger" | "model" | "code";

interface Step {
  id: string;
  title: string;
  short: string;
  actor: Actor;
  detail: string;
  stops?: string;
}

/**
 * The agent's lifecycle, read from the implemented loop (open, plan, execute, reassess, diagnose or
 * abstain), its plan validation, its stopping policy and its report validation. It describes
 * what the code does, not what any one session did. A session's own steps are on its page.
 */
const STEPS: Step[] = [
  {
    id: "trigger",
    title: "Trigger",
    short: "An incident, its scope and a time window.",
    actor: "trigger",
    detail:
      "An investigation starts from one named incident: a faithfulness block cluster, a judge disagreement cluster, a Red Team miss, an error surge, judge drift or a single trace. Starting one is always an explicit request. Opening a stored session never starts one.",
    stops:
      "The first read is of the one source the investigation cannot do without. If that source is down twice, or matched nothing, the agent abstains here.",
  },
  {
    id: "plan",
    title: "Plan",
    short: "The model proposes rival hypotheses.",
    actor: "model",
    detail:
      "The model is the only part that is not code. It proposes two to four rival hypotheses, each with predictions and the query that would test it. Validation keeps only the queries that tell two hypotheses apart and drops everything else. Nothing the model writes can later be cited as evidence.",
    stops:
      "A plan with fewer than two usable hypotheses ends the investigation as an abstention.",
  },
  {
    id: "execute",
    title: "Execute",
    short: "Code runs the queries, read-only.",
    actor: "code",
    detail:
      "Code runs the surviving queries through nine read-only tools, each under a call ceiling and a deadline. A query that could not run is recorded as unavailable. It is never counted as an empty result. The agent has no tool that writes anything.",
    stops:
      "A ceiling on tool calls, model calls, rounds or time ends the run with a stated reason.",
  },
  {
    id: "assess",
    title: "Assess",
    short: "Deterministic checks read each prediction.",
    actor: "code",
    detail:
      "Each prediction is judged only by the records of the query it names. Another query of the same tool cannot satisfy or contradict it, and a prediction whose query never ran stays unknown. A review then challenges the leading hypothesis against the counter-evidence it retrieved. When budget remains and the evidence did not settle it, the agent plans once more.",
  },
  {
    id: "validate",
    title: "Validate",
    short: "Every citation must trace to a query.",
    actor: "code",
    detail:
      "Every record a claim cites must be one that an executed query returned. A record that was merely queried is not evidence, and a controlled Red Team result shows how a defense behaves but never what caused an incident.",
    stops:
      "A report that fails validation is replaced by an abstention. It is never shipped.",
  },
  {
    id: "conclude",
    title: "Conclude or abstain",
    short: "A best-supported cause, or an honest no.",
    actor: "code",
    detail:
      "A diagnosis is a best-supported hypothesis. It is checked against its own predictions and the counter-evidence, and it is never presented as proven. An abstention is a complete, stored result that says which source was missing or why the records supported no cause.",
  },
];

const ACTOR_LABEL: Record<Actor, string> = {
  trigger: "A request",
  model: "Model proposes",
  code: "Code decides",
};

const ACTOR_STYLE: Record<Actor, string> = {
  trigger: "text-text-secondary border-border-strong",
  model: "text-signal border-signal/40 bg-signal/10",
  code: "text-text-primary border-border-strong bg-surface",
};

/** The lifecycle as six selectable steps. Selection moves an explanation below, nothing else.
 * It is a stepper and not tabs, because the order is the point. */
export function AgentLifecycle() {
  const [selected, setSelected] = useState("trigger");
  const current = STEPS.find((s) => s.id === selected) ?? STEPS[0];
  const index = STEPS.indexOf(current);

  return (
    <div>
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        {STEPS.map((step, i) => {
          const active = step.id === selected;
          return (
            <li key={step.id} className="relative">
              <button
                type="button"
                aria-pressed={active}
                aria-controls="agent-step-detail"
                onClick={() => setSelected(step.id)}
                className={`lift flex h-full min-h-11 w-full flex-col items-start gap-2 rounded-xl border p-4 text-left ${
                  active
                    ? "border-line-active bg-surface-high"
                    : "border-line bg-background-elevated/70"
                }`}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="text-text-tertiary font-mono text-sm tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span
                    className={`rounded-md border px-1.5 py-0.5 text-xs font-medium ${ACTOR_STYLE[step.actor]}`}
                  >
                    {ACTOR_LABEL[step.actor]}
                  </span>
                </span>
                <span className="text-text-primary text-lg font-semibold tracking-tight text-balance">
                  {step.title}
                </span>
                <span className="text-text-secondary text-base leading-snug">
                  {step.short}
                </span>
              </button>
              {active ? (
                <span
                  aria-hidden="true"
                  className="bg-accent absolute inset-x-4 -bottom-px h-0.5 rounded-full"
                />
              ) : null}
            </li>
          );
        })}
      </ol>

      <div
        id="agent-step-detail"
        role="region"
        aria-live="polite"
        aria-label={`Step ${index + 1}: ${current.title}`}
        className="border-border bg-background-elevated/60 swap-in mt-3 grid gap-6 rounded-xl border p-5 sm:p-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"
        key={current.id}
      >
        <div>
          <p className="eyebrow">
            Step {index + 1} of {STEPS.length}
          </p>
          <h3 className="text-text-primary mt-2 text-xl font-semibold tracking-tight">
            {current.title}
          </h3>
          <p className="text-text-secondary mt-2 text-base leading-relaxed text-pretty">
            {current.detail}
          </p>
        </div>
        <div className="border-border lg:border-l lg:pl-6">
          <p className="eyebrow">Where it can stop</p>
          <p className="text-text-primary mt-2 text-base leading-relaxed text-pretty">
            {current.stops ??
              "No exit starts here. The steps before it hold the stops, and this step only reads what they left."}
          </p>
        </div>
      </div>
    </div>
  );
}
