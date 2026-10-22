"use client";

import Link from "next/link";
import { ConceptIcon, type ConceptId } from "@/components/concept-icons";
import { stageAnchor, type NodeId } from "@/lib/architecture-data";
import { useIsDesktop } from "@/lib/use-is-desktop";

interface Stage {
  id: ConceptId;
  title: string;
  body: string;
  /** A request-path stage on the architecture page, or a route of its own. */
  to: { stage: NodeId } | { href: string };
  cta: string;
  tone: "accent" | "signal" | "neutral";
}

const STAGES: Stage[] = [
  {
    id: "guard",
    title: "Guard",
    body: "Input rails check the question and output rails check the answer. A rail that errors stops the request.",
    to: { href: "/investigations?status=blocked" },
    cta: "See blocked requests",
    tone: "accent",
  },
  {
    id: "retrieve",
    title: "Retrieve",
    body: "Closest filing chunks come from pgvector. Every chunk is checked for trust, injection and PII first.",
    to: { stage: "retrieval" },
    cta: "See how retrieval works",
    tone: "accent",
  },
  {
    id: "generate",
    title: "Generate",
    body: "One model call answers in JSON under a time budget and a circuit breaker.",
    to: { href: "/generation" },
    cta: "See how generation is bounded",
    tone: "accent",
  },
  {
    id: "judge",
    title: "Judge",
    body: "A flash judge scores every delivered answer. About one in ten gets a frontier second opinion.",
    to: { href: "/overview#coverage-heading" },
    cta: "See judge coverage",
    tone: "signal",
  },
  {
    id: "investigate",
    title: "Agent",
    body: "When something goes wrong, the Incident Response Agent examines the stored evidence and reports only what the records support.",
    to: { href: "/agent" },
    cta: "Open the Agent",
    tone: "neutral",
  },
];

/** The wide pipeline and the narrow outline each carry their own copy of a stage id, and only
 * the one for the current width is displayed, so the link picks that one. Rendering on the
 * server gives the outline id until the page hydrates. */
export function stageHref(to: Stage["to"], desktop: boolean): string {
  if ("href" in to) return to.href;
  return `/architecture#${stageAnchor(to.stage, desktop ? "wide" : "outline")}`;
}

const TONE_TEXT = {
  accent: "text-accent",
  signal: "text-signal",
  neutral: "text-text-primary",
} as const;

const TONE_BAR = {
  accent: "from-accent/70",
  signal: "from-signal/70",
  neutral: "from-text-primary/50",
} as const;

const TONE_LIFT = {
  accent: "lift-accent",
  signal: "lift-signal",
  neutral: "lift-accent",
} as const;

// The `.lift` hover border and background are in the components layer, so the
// card's own border and background utilities win. These restore the tone
// response on hover with variants that sit above them.
const TONE_HOVER = {
  accent: "hover:border-accent/40 hover:bg-surface-hover",
  signal: "hover:border-signal/40 hover:bg-surface-hover",
  neutral: "hover:border-accent/40 hover:bg-surface-hover",
} as const;

/**
 * Five stages of one answer's life, in order, each opening its own destination, and no two
 * share a diagram. Guard opens the blocked requests with the rail that stopped each, Generate
 * opens the generation page (the bounds around the model call and what the schema rail
 * rejected), Judge opens the evaluation coverage and Agent opens the Agent. Retrieve has no
 * product view of its own, since no stored data isolates a retrieval, so it opens its stage on
 * the architecture page and is the only card that opens a diagram. Red Team sits below as its
 * own line because it is not part of any request. Static copy only: no counts, no status.
 */
export function StageCards() {
  const desktop = useIsDesktop();
  return (
    <>
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {STAGES.map((stage, i) => (
          <li key={stage.id} className="relative">
            <Link
              href={stageHref(stage.to, desktop)}
              className={`lift ${TONE_LIFT[stage.tone]} ${TONE_HOVER[stage.tone]} reveal-host border-line bg-background-elevated/70 group relative flex h-full flex-col overflow-hidden rounded-xl border p-5`}
            >
              <span
                aria-hidden="true"
                className={`absolute inset-x-0 top-0 h-px bg-gradient-to-r ${TONE_BAR[stage.tone]} to-transparent`}
              />
              <span className="flex items-center justify-between">
                <span
                  className={`border-line-hover bg-surface flex h-10 w-10 items-center justify-center rounded-lg border transition-colors duration-[var(--dur-base)] ${TONE_TEXT[stage.tone]}`}
                >
                  <ConceptIcon id={stage.id} className="h-5 w-5" />
                </span>
                <span
                  aria-hidden="true"
                  className="text-text-tertiary font-mono text-sm tabular-nums"
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
              </span>
              <h3 className="text-text-primary mt-5 text-lg font-semibold tracking-tight">
                {stage.title}
              </h3>
              <p className="text-text-secondary mt-2 flex-1 text-base leading-relaxed">
                {stage.body}
              </p>
              <span
                className={`reveal-on-hover mt-4 inline-flex min-h-6 items-center gap-1.5 text-sm font-medium ${TONE_TEXT[stage.tone]}`}
              >
                {stage.cta}
                <span aria-hidden="true">→</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
      <div className="border-line mt-3 flex flex-col gap-1 rounded-xl border border-dashed px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
        <p className="text-text-secondary text-base leading-relaxed">
          <span className="text-text-primary font-medium">
            Outside the request path.
          </span>{" "}
          Red Team runs written attack scenarios against these defenses and
          keeps what each one caught or missed.
        </p>
        <Link
          href="/red-team"
          className="text-accent hover:text-text-primary inline-flex min-h-11 shrink-0 items-center gap-1.5 text-base font-medium transition-colors sm:text-sm"
        >
          Open Red Team
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </>
  );
}
