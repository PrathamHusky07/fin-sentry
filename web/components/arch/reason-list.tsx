"use client";

import { useState } from "react";
import type { Reason } from "@/lib/architecture-layers";

/** The "Why" reasons for a layer as progressive disclosure: each is a
 * disclosure that opens to its full explanation. The first starts open so
 * the section is never a wall of closed rows, and every body is in the page
 * whether or not it is open. */
export function ReasonList({
  reasons,
  layerId,
}: {
  reasons: Reason[];
  layerId: string;
}) {
  const [open, setOpen] = useState<Set<number>>(() => new Set([0]));

  function toggle(i: number) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <ul className="grid items-start gap-x-10 md:grid-cols-2">
      {reasons.map((reason, i) => {
        const isOpen = open.has(i);
        const id = `${layerId}-reason-${i}`;
        return (
          <li key={reason.term} className="border-line border-t">
            <h3>
              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={id}
                onClick={() => toggle(i)}
                className="group flex min-h-14 w-full items-center justify-between gap-4 py-4 text-left"
              >
                <span
                  className={`text-base font-semibold transition-colors duration-[var(--dur-fast)] ${isOpen ? "text-text-primary" : "text-text-secondary group-hover:text-text-primary"}`}
                >
                  {reason.term}
                </span>
                <svg
                  viewBox="0 0 20 20"
                  className={`text-text-tertiary h-5 w-5 shrink-0 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${isOpen ? "rotate-180" : ""}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  aria-hidden="true"
                >
                  <path d="M5 8l5 5 5-5" />
                </svg>
              </button>
            </h3>
            <div
              id={id}
              className={`grid transition-[grid-template-rows,opacity] duration-[var(--dur-base)] ease-[var(--ease)] ${isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}
            >
              <div className="overflow-hidden" inert={!isOpen}>
                <p className="text-text-secondary pb-5 text-base leading-relaxed">
                  {reason.body}
                </p>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
