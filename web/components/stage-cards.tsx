import { ConceptIcon, type ConceptId } from "@/components/concept-icons";
import { StageLink } from "@/components/stage-link";
import { stageAnchor } from "@/lib/architecture-data";

interface Stage {
  id: ConceptId;
  title: string;
  body: string;
  href: string;
  /** Used below the wide breakpoint, where the destination shows an outline. */
  narrowHref?: string;
  cta: string;
  tone: "accent" | "signal" | "neutral";
}

const STAGES: Stage[] = [
  {
    id: "guard",
    title: "Guard",
    body: "Input rails check the question and output rails check the answer. A rail that errors blocks the request.",
    href: `/architecture#${stageAnchor("input")}`,
    narrowHref: `/architecture#${stageAnchor("input", "outline")}`,
    cta: "See the rails",
    tone: "accent",
  },
  {
    id: "retrieve",
    title: "Retrieve",
    body: "Closest filing chunks come from pgvector. Every chunk is checked for trust, injection and PII first.",
    href: `/architecture#${stageAnchor("retrieval")}`,
    narrowHref: `/architecture#${stageAnchor("retrieval", "outline")}`,
    cta: "See retrieval",
    tone: "accent",
  },
  {
    id: "generate",
    title: "Generate",
    body: "One model call answers in JSON under a time budget and a circuit breaker.",
    href: `/architecture#${stageAnchor("generation")}`,
    narrowHref: `/architecture#${stageAnchor("generation", "outline")}`,
    cta: "See the budget",
    tone: "accent",
  },
  {
    id: "judge",
    title: "Judge",
    body: "A flash judge scores every delivered answer. About one in ten gets a frontier second opinion.",
    href: "/architecture#evaluation-plane",
    cta: "See the judges",
    tone: "signal",
  },
  {
    id: "investigate",
    title: "Investigate",
    body: "Every execution stays as one row with its outcome, chunks, scores and reasoning.",
    href: "/investigations",
    cta: "Open the workspace",
    tone: "neutral",
  },
];

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
 * Five stages of one answer's life, in order. Each card opens the part of
 * the product that shows it. Static copy only: no counts, no status.
 */
export function StageCards() {
  return (
    <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {STAGES.map((stage, i) => (
        <li key={stage.id} className="relative">
          <StageLink
            href={stage.href}
            narrowHref={stage.narrowHref}
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
          </StageLink>
        </li>
      ))}
    </ol>
  );
}
