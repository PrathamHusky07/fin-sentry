"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { DECISIONS, type Decision } from "@/lib/decisions";

const TOTAL = DECISIONS.length;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** One decision as an argument: the problem, what was decided, then what it
 * cost and what it made true. The words are the persisted text, unedited. */
function DecisionBody({ decision }: { decision: Decision }) {
  return (
    <div className="space-y-7">
      <div>
        <p className="text-text-tertiary text-sm">Problem</p>
        <p className="text-text-secondary mt-1.5 text-base leading-relaxed">
          {decision.problem}
        </p>
      </div>
      <div className="border-accent/60 border-l-2 pl-5">
        <p className="text-accent text-sm">Decision</p>
        <p className="text-text-primary mt-1.5 text-lg leading-relaxed">
          {decision.decision}
        </p>
      </div>
      <div className="grid gap-x-8 gap-y-7 sm:grid-cols-2">
        <div>
          <p className="text-text-tertiary text-sm">Tradeoff</p>
          <p className="text-text-secondary mt-1.5 text-base leading-relaxed">
            {decision.tradeoff}
          </p>
        </div>
        <div>
          <p className="text-text-tertiary text-sm">Consequence</p>
          <p className="text-text-secondary mt-1.5 text-base leading-relaxed">
            {decision.consequence}
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * The six engineering decisions as a navigator. The titles are real
 * controls on the left; the selected decision opens on the right with all
 * four parts of its argument. A selection plate slides between titles, and
 * the panels share one grid cell so the height never jumps. Below lg the
 * same selection becomes an accordion, because a two-column navigator does
 * not fit a phone. Every word of every decision is in the page either way.
 */
export function DecisionNavigator() {
  const [selected, setSelected] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function move(to: number) {
    const next = (to + TOTAL) % TOTAL;
    setSelected(next);
    buttons.current[next]?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLUListElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      move(selected + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(selected - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      move(0);
    } else if (e.key === "End") {
      e.preventDefault();
      move(TOTAL - 1);
    }
  }

  return (
    <div>
      <div className="hidden gap-14 lg:grid lg:grid-cols-[minmax(0,23rem)_minmax(0,1fr)]">
        <div className="relative">
          <span
            aria-hidden="true"
            className="border-line-hover bg-surface-active/80 absolute inset-x-0 top-0 rounded-xl border shadow-[0_0_0_1px_color-mix(in_srgb,var(--accent)_10%,transparent),0_18px_40px_-26px_var(--glow-accent)] transition-transform duration-[var(--dur-base)] ease-[var(--ease)]"
            style={{
              height: `${100 / TOTAL}%`,
              transform: `translateY(${selected * 100}%)`,
            }}
          >
            <span className="bg-accent absolute top-3 bottom-3 left-0 w-0.5 rounded-full" />
          </span>
          <ul
            onKeyDown={onKeyDown}
            className="relative grid h-full"
            style={{ gridAutoRows: "1fr" }}
          >
            {DECISIONS.map((decision, i) => (
              <li key={decision.title}>
                <button
                  ref={(el) => {
                    buttons.current[i] = el;
                  }}
                  type="button"
                  id={`decision-tab-${i}`}
                  aria-current={selected === i ? "true" : undefined}
                  aria-controls={`decision-panel-${i}`}
                  onClick={() => setSelected(i)}
                  className={`flex h-full min-h-14 w-full items-start gap-4 rounded-xl px-5 py-4 text-left transition-colors duration-[var(--dur-fast)] ${
                    selected === i
                      ? "text-text-primary"
                      : "text-text-secondary hover:text-text-primary"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 font-mono text-sm tabular-nums transition-colors ${selected === i ? "text-accent" : "text-text-tertiary"}`}
                  >
                    {pad(i + 1)}
                  </span>
                  <span className="text-base leading-snug font-medium text-balance">
                    {decision.title}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="border-line bg-background-elevated/60 grid rounded-2xl border p-8 xl:p-10">
          {DECISIONS.map((decision, i) => {
            const open = selected === i;
            return (
              <div
                key={decision.title}
                id={`decision-panel-${i}`}
                role="group"
                aria-labelledby={`decision-tab-${i}`}
                aria-hidden={!open}
                inert={!open}
                className={`col-start-1 row-start-1 transition-[opacity,transform] duration-[var(--dur-base)] ease-[var(--ease)] ${
                  open
                    ? "translate-y-0 opacity-100"
                    : "pointer-events-none translate-y-2 opacity-0"
                }`}
              >
                <p className="eyebrow">
                  Decision {pad(i + 1)} of {pad(TOTAL)}
                </p>
                <h3 className="text-text-primary mt-2 mb-7 text-2xl leading-tight font-semibold tracking-tight text-balance">
                  {decision.title}
                </h3>
                <DecisionBody decision={decision} />
              </div>
            );
          })}
        </div>
      </div>

      <ol className="lg:hidden">
        {DECISIONS.map((decision, i) => {
          const open = selected === i;
          return (
            <li key={decision.title} className="border-line border-b">
              <h3>
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={`decision-m-${i}`}
                  onClick={() => setSelected(i)}
                  className="flex min-h-14 w-full items-start gap-4 py-4 text-left"
                >
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 font-mono text-sm tabular-nums ${open ? "text-accent" : "text-text-tertiary"}`}
                  >
                    {pad(i + 1)}
                  </span>
                  <span
                    className={`flex-1 text-lg leading-snug font-semibold text-balance ${open ? "text-text-primary" : "text-text-secondary"}`}
                  >
                    {decision.title}
                  </span>
                </button>
              </h3>
              <div
                id={`decision-m-${i}`}
                className={`grid transition-[grid-template-rows,opacity] duration-[var(--dur-base)] ease-[var(--ease)] ${
                  open
                    ? "grid-rows-[1fr] opacity-100"
                    : "grid-rows-[0fr] opacity-0"
                }`}
              >
                <div className="overflow-hidden" inert={!open}>
                  <div className="pb-7 pl-9">
                    <DecisionBody decision={decision} />
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
