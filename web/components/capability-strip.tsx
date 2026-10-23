"use client";

import type { ReactNode } from "react";
import { ConceptIcon } from "@/components/concept-icons";

interface Capability {
  title: string;
  /** What the platform does, in words that hold whether or not a backend is reachable. */
  summary: string;
  /** How it works, shown on hover and focus. Nothing here is a current reading. */
  detail: string;
  icon: ReactNode;
}

/** Two arcs that start together and part: the one concept the shared glyph set has no icon for. */
function DisagreementIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="h-5 w-5"
    >
      <path d="M4 12h4" />
      <path d="M8 12c3 0 4-6 8-6h4" />
      <path d="M8 12c3 0 4 6 8 6h4" />
    </svg>
  );
}

const CAPABILITIES: Capability[] = [
  {
    title: "Quality signals",
    summary: "Faithfulness, answer relevance and context relevance",
    detail:
      "The flash judge scores every answer it evaluates on these three measures. The Evaluation telemetry section summarizes its latest verdicts.",
    icon: <ConceptIcon id="judge" />,
  },
  {
    title: "Judge calibration",
    summary: "Agreement against labeled examples",
    detail:
      "The frontier judge is compared with human-labeled financial examples and summarized as Cohen’s kappa against a drift policy. The Calibration section shows the stored reading.",
    icon: <ConceptIcon id="calibrate" />,
  },
  {
    title: "Disagreement analysis",
    summary: "Inspect where the two judge tiers differ",
    detail:
      "A trace that the flash and frontier judges scored far apart can be opened in Investigations and compared side by side. Whether any exist depends on the stored record.",
    icon: <DisagreementIcon />,
  },
  {
    title: "Evidence-backed investigations",
    summary: "Decisions traced to recorded evidence",
    detail:
      "Each investigator case lists the evidence behind its decision. Stored cases are open to read in Agent, and running a new one needs the backend.",
    icon: <ConceptIcon id="investigate" />,
  },
];

/** Which edge each cell's panel hangs from, so it stays inside the viewport. */
const PEEK_SIDE = [
  "left-0",
  "left-0 lg:left-auto lg:right-0 xl:left-0 xl:right-auto",
  "left-0 lg:left-auto lg:right-0",
  "left-0 sm:left-auto sm:right-0",
] as const;

/**
 * What the platform measures, as four plain statements. It says nothing about the current state
 * of any service, so it reads the same with the backend running, stopped or never deployed: no
 * status dot, no timestamp and no connected or live wording. The live readings stay in the
 * sections below, each with its own window and staleness.
 */
export function CapabilityStrip() {
  return (
    <div className="border-border bg-background/90 border-b backdrop-blur">
      <ul
        aria-label="What Live Operations covers"
        className="divide-border mx-auto grid max-w-7xl grid-cols-1 divide-y px-4 sm:grid-cols-2 sm:divide-y-0 sm:px-8 lg:grid-cols-4 lg:divide-x"
      >
        {CAPABILITIES.map((item, i) => (
          <li
            key={item.title}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Escape") e.currentTarget.blur();
            }}
            className="reveal-host hover:bg-surface-hover/70 relative flex min-h-11 items-start gap-3 px-3 py-3.5 transition-colors duration-[var(--dur-base)] lg:py-4"
          >
            <span className="text-text-tertiary mt-0.5 shrink-0">
              {item.icon}
            </span>
            <span className="min-w-0">
              <span className="text-text-primary block text-sm font-medium">
                {item.title}
              </span>
              <span className="text-text-tertiary mt-0.5 block text-sm leading-snug">
                {item.summary}
              </span>
            </span>
            <span
              className={`peek floating top-full mt-1 w-72 max-w-[calc(100vw-2rem)] rounded-lg px-3.5 py-2.5 text-sm leading-snug font-normal ${PEEK_SIDE[i]}`}
            >
              <span className="text-text-secondary block">{item.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
