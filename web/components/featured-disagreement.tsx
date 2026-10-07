"use client";

import Link from "next/link";
import { useState, type CSSProperties, type PointerEvent } from "react";
import type {
  FlashJudgeView,
  TraceDetailResponse,
  TraceListItem,
} from "@/lib/trace-api";

type Side = "flash" | "frontier";

const SIDE_LABEL: Record<Side, string> = {
  flash: "Flash judge, faithfulness",
  frontier: "Frontier judge, faithfulness",
};

function metric(score: number | null, status: string | null): string {
  if (score === null) return status ? `not scored, ${status}` : "not scored";
  return `${score.toFixed(3)}${status ? `, ${status}` : ""}`;
}

/** The flash judge's persisted record: a score and a status per metric. The
 * trace API carries no written reasoning for this tier, so none is shown. */
function FlashRecord({ flash }: { flash: FlashJudgeView | null }) {
  if (!flash) {
    return (
      <p className="text-text-secondary text-base">
        The flash judge’s record could not be loaded for this trace.
      </p>
    );
  }
  return (
    <>
      <p className="text-text-tertiary text-sm">
        The flash judge’s persisted record
      </p>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-base">
        <dt className="text-text-secondary">Faithfulness</dt>
        <dd className="tabular-metric text-text-primary">
          {metric(flash.faithfulness_score, flash.faithfulness_status)}
        </dd>
        <dt className="text-text-secondary">Answer relevance</dt>
        <dd className="tabular-metric text-text-primary">
          {metric(flash.answer_relevance_score, flash.answer_relevance_status)}
        </dd>
        <dt className="text-text-secondary">Context relevance</dt>
        <dd className="tabular-metric text-text-primary">
          {metric(
            flash.context_relevance_score,
            flash.context_relevance_status,
          )}
        </dd>
      </dl>
      <p className="text-text-tertiary mt-3 text-sm">
        This tier persists scores and statuses, not written reasoning.
      </p>
    </>
  );
}

function ScoreButton({
  side,
  score,
  active,
  dimmed,
  pinned,
  onHover,
  onPin,
}: {
  side: Side;
  score: number;
  active: boolean;
  dimmed: boolean;
  pinned: boolean;
  onHover: (side: Side | null) => void;
  onPin: (side: Side) => void;
}) {
  const color = side === "flash" ? "text-accent" : "text-disagreement";
  const bar = side === "flash" ? "bg-accent" : "bg-disagreement";
  return (
    <button
      type="button"
      aria-pressed={pinned}
      onPointerEnter={(e: PointerEvent) => {
        if (e.pointerType === "mouse") onHover(side);
      }}
      onPointerLeave={(e: PointerEvent) => {
        if (e.pointerType === "mouse") onHover(null);
      }}
      onFocus={(e) => {
        if (e.currentTarget.matches(":focus-visible")) onHover(side);
      }}
      onBlur={() => onHover(null)}
      onClick={() => onPin(side)}
      className={`group min-h-11 rounded-xl p-3 text-left transition-[opacity,background-color] duration-[var(--dur-base)] ease-[var(--ease-soft)] sm:p-4 ${
        dimmed ? "opacity-35" : "opacity-100"
      } ${active ? "bg-surface-hover/60" : ""}`}
    >
      <span className="text-text-secondary block text-sm">
        {SIDE_LABEL[side]}
      </span>
      <span
        className={`tabular-metric mt-1 block text-6xl leading-none font-semibold tracking-tighter sm:text-8xl ${color}`}
      >
        {score.toFixed(3)}
      </span>
      <span
        aria-hidden="true"
        className={`mt-4 block h-0.5 origin-left rounded-full transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${bar} ${active ? "scale-x-100" : "scale-x-[0.18]"}`}
      />
    </button>
  );
}

/** The two scores on one shared 0 to 1 axis, with the gap between them
 * filled. The gap is derived: the absolute difference of the two persisted
 * scores. */
function ScoreAxis({
  flash,
  frontier,
  side,
}: {
  flash: number;
  frontier: number;
  side: Side | null;
}) {
  const low = Math.min(flash, frontier);
  const gap = Math.abs(flash - frontier);
  const at = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%`;
  return (
    <div className="px-3 sm:px-4">
      <div
        role="img"
        aria-label={`On a scale from 0 to 1, the flash judge scored ${flash.toFixed(3)} and the frontier judge scored ${frontier.toFixed(3)}, ${gap.toFixed(3)} apart.`}
        className="relative mx-2.5 h-3"
      >
        <span className="bg-surface-high absolute inset-0 rounded-full" />
        <span
          className="enter-sweep bg-disagreement/45 absolute inset-y-0 rounded-full"
          style={
            {
              left: at(low),
              width: `${gap * 100}%`,
              "--sweep-delay": "300ms",
            } as CSSProperties
          }
        />
        {(
          [
            ["flash", flash, "bg-accent"],
            ["frontier", frontier, "bg-disagreement"],
          ] as const
        ).map(([name, value, bg]) => (
          <span
            key={name}
            className="absolute top-1/2"
            style={{ left: at(value) }}
          >
            <span
              className={`border-background absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${bg} h-5 w-5 ${side === name ? "scale-125" : ""}`}
            />
          </span>
        ))}
      </div>
      <div className="text-text-tertiary mt-3 flex items-center justify-between text-sm">
        <span className="tabular-metric">0</span>
        <span className="text-disagreement font-medium">
          <span className="tabular-metric">{gap.toFixed(3)}</span> apart
        </span>
        <span className="tabular-metric">1</span>
      </div>
    </div>
  );
}

/**
 * The finding the second judge tier exists for, shown as one case: the two
 * faithfulness scores that split on it, large and on a shared axis, then the
 * question, the returned answer and the evidence behind each side. Pointing
 * at, focusing or tapping a score lights that side and dims the other, and
 * the panel beside the answer shows that judge's persisted record. Everything
 * comes from the persisted trace. When the trace detail is unavailable the
 * block says so and keeps the question and the link, and never invents a
 * score or an answer.
 */
export function FeaturedDisagreement({
  trace,
  detail,
  others,
  othersIsFloor = false,
}: {
  trace: TraceListItem;
  detail: TraceDetailResponse | null;
  others: number;
  /** True when the disagreement query hit its limit, so `others` is a floor. */
  othersIsFloor?: boolean;
}) {
  const [hovered, setHovered] = useState<Side | null>(null);
  const [pinned, setPinned] = useState<Side | null>(null);
  const side = hovered ?? pinned;

  const flash = detail?.flash?.faithfulness_score ?? null;
  const frontier = detail?.frontier.evidence?.faithfulness_score ?? null;
  const reasoning = detail?.frontier.evidence?.rubric_reasoning ?? null;
  const answer = detail?.answer ?? null;

  return (
    <section
      aria-labelledby="featured-heading"
      className="state-field border-disagreement/40 bg-disagreement/[0.04] relative overflow-hidden rounded-2xl border p-6 sm:p-8"
      style={{ "--field": "var(--disagreement)" } as CSSProperties}
    >
      <p className="text-disagreement text-sm font-medium">
        The case the second judge exists for
      </p>
      <h2
        id="featured-heading"
        className="text-text-primary mt-2 max-w-3xl text-2xl font-semibold tracking-tight text-balance sm:text-3xl"
      >
        {trace.query}
      </h2>

      {flash !== null && frontier !== null ? (
        <div className="mt-8">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-6">
            <ScoreButton
              side="flash"
              score={flash}
              active={side === "flash"}
              dimmed={side === "frontier"}
              pinned={pinned === "flash"}
              onHover={setHovered}
              onPin={(s) => setPinned((p) => (p === s ? null : s))}
            />
            <ScoreButton
              side="frontier"
              score={frontier}
              active={side === "frontier"}
              dimmed={side === "flash"}
              pinned={pinned === "frontier"}
              onHover={setHovered}
              onPin={(s) => setPinned((p) => (p === s ? null : s))}
            />
          </div>
          <div className="mt-6">
            <ScoreAxis flash={flash} frontier={frontier} side={side} />
          </div>
        </div>
      ) : (
        <p className="text-text-secondary mt-8 text-base">
          The two persisted scores could not be loaded for this trace.
        </p>
      )}

      <div className="mt-10 grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div>
          <p className="text-text-tertiary text-sm">The system answered</p>
          {answer ? (
            <blockquote className="border-text-tertiary text-text-primary mt-2 border-l-2 pl-4 text-lg leading-relaxed whitespace-pre-line">
              {answer}
            </blockquote>
          ) : (
            <p className="text-text-secondary mt-2 text-base">
              The answer text could not be loaded for this trace.
            </p>
          )}
        </div>

        <div className="grid">
          <div
            aria-hidden={side === "flash"}
            className={`col-start-1 row-start-1 transition-opacity duration-[var(--dur-base)] ease-[var(--ease-soft)] ${side === "flash" ? "pointer-events-none opacity-0" : "opacity-100"}`}
          >
            {reasoning ? (
              <p className="text-text-secondary text-base leading-relaxed">
                <span className="text-text-tertiary block text-sm">
                  The frontier judge’s reasoning
                </span>
                {reasoning}
              </p>
            ) : (
              <p className="text-text-secondary text-base">
                No written reasoning is persisted for the frontier judge on this
                trace.
              </p>
            )}
          </div>
          <div
            aria-hidden={side !== "flash"}
            className={`col-start-1 row-start-1 transition-opacity duration-[var(--dur-base)] ease-[var(--ease-soft)] ${side === "flash" ? "opacity-100" : "pointer-events-none opacity-0"}`}
          >
            <FlashRecord flash={detail?.flash ?? null} />
          </div>
        </div>
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2">
        <Link
          href={`/investigations?trace=${trace.app_trace_id}`}
          className="bg-text-primary text-background hover:bg-text-primary/90 inline-flex min-h-11 items-center rounded-lg px-5 text-sm font-medium shadow-[0_10px_28px_-14px_var(--glow-disagreement)] transition-[background-color,box-shadow] duration-[var(--dur-base)] hover:shadow-[0_14px_34px_-14px_var(--glow-disagreement)]"
        >
          Open the full trace
        </Link>
        {others > 0 ? (
          <Link
            href="/investigations?disagreement=true"
            className="text-accent hover:text-text-primary min-h-11 content-center text-sm underline underline-offset-4"
          >
            {others}
            {othersIsFloor ? "+" : ""} more{" "}
            {others === 1 ? "disagreement" : "disagreements"}
          </Link>
        ) : null}
      </div>
    </section>
  );
}
