"use client";

import { useState, type PointerEvent } from "react";
import type {
  FlashJudgeView,
  FrontierEvidenceView,
  TraceDetailResponse,
} from "@/lib/trace-api";

export interface DisagreementScores {
  flashScore: number;
  frontierScore: number;
}

type Side = "flash" | "frontier";

/** Two scores on one 0 to 1 axis, with the gap between them filled. The
 * distance is the finding, so it is drawn and not only stated. When a judge
 * is active its marker grows and the gap brightens. */
function ScoreScale({
  flash,
  frontier,
  side,
}: {
  flash: number;
  frontier: number;
  side: Side | null;
}) {
  const lo = Math.min(flash, frontier) * 100;
  const hi = Math.max(flash, frontier) * 100;
  return (
    <div
      role="img"
      aria-label={`Faithfulness on a scale from 0 to 1: flash ${flash.toFixed(3)}, frontier ${frontier.toFixed(3)}.`}
      className="relative mx-3 mt-9 mb-9 h-3"
    >
      <div className="bg-surface-high absolute inset-0 rounded-full" />
      <div
        className={`enter-sweep absolute inset-y-0 transition-colors duration-[var(--dur-base)] ${side ? "bg-disagreement/80" : "bg-disagreement/50"}`}
        style={{ left: `${lo}%`, width: `${hi - lo}%` }}
      />
      {[
        { at: flash, name: "Flash", id: "flash", ring: "border-accent" },
        {
          at: frontier,
          name: "Frontier",
          id: "frontier",
          ring: "border-disagreement",
        },
      ].map((m) => (
        <div
          key={m.name}
          className="absolute top-1/2"
          style={{ left: `${m.at * 100}%` }}
        >
          <span
            aria-hidden="true"
            className={`bg-background absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${m.ring} ${side === m.id ? "scale-150" : ""}`}
          />
          <span className="text-text-secondary absolute top-3 -translate-x-1/2 text-xs whitespace-nowrap">
            {m.name}
          </span>
        </div>
      ))}
      <span className="text-text-tertiary absolute -top-5 -left-1 font-mono text-[11px]">
        0
      </span>
      <span className="text-text-tertiary absolute -top-5 -right-1 font-mono text-[11px]">
        1
      </span>
    </div>
  );
}

/** The paired readings at the heart of a disagreement: both persisted
 * faithfulness scores, large, with the distance between them drawn. Pointing
 * at, focusing or tapping a score lights that judge and dims the other. */
function DisagreementDuel({
  scores,
  side,
  onHover,
  onPin,
  pinned,
}: {
  scores: DisagreementScores;
  side: Side | null;
  onHover: (side: Side | null) => void;
  onPin: (side: Side) => void;
  pinned: Side | null;
}) {
  const cells: { id: Side; label: string; value: number; color: string }[] = [
    {
      id: "flash",
      label: "Flash judge",
      value: scores.flashScore,
      color: "text-accent",
    },
    {
      id: "frontier",
      label: "Frontier judge",
      value: scores.frontierScore,
      color: "text-disagreement",
    },
  ];
  return (
    <div>
      <p className="text-disagreement text-base font-semibold">
        The two judge tiers disagree on faithfulness
      </p>
      <div className="mt-5 grid grid-cols-2 gap-3">
        {cells.map((cell) => (
          <button
            key={cell.id}
            type="button"
            aria-pressed={pinned === cell.id}
            onPointerEnter={(e: PointerEvent) => {
              if (e.pointerType === "mouse") onHover(cell.id);
            }}
            onPointerLeave={(e: PointerEvent) => {
              if (e.pointerType === "mouse") onHover(null);
            }}
            onFocus={(e) => {
              if (e.currentTarget.matches(":focus-visible")) onHover(cell.id);
            }}
            onBlur={() => onHover(null)}
            onClick={() => onPin(cell.id)}
            className={`min-h-11 rounded-lg p-2 text-left transition-[opacity,background-color] duration-[var(--dur-base)] ease-[var(--ease-soft)] ${side !== null && side !== cell.id ? "opacity-35" : "opacity-100"} ${side === cell.id ? "bg-surface-hover/60" : ""}`}
          >
            <span className="text-text-secondary block text-sm">
              {cell.label}
            </span>
            <span
              className={`tabular-metric mt-1 block text-5xl font-semibold tracking-tight ${cell.color}`}
            >
              {cell.value.toFixed(3)}
            </span>
          </button>
        ))}
      </div>
      <ScoreScale
        flash={scores.flashScore}
        frontier={scores.frontierScore}
        side={side}
      />
    </div>
  );
}

function ChunkList({ label, ids }: { label: string; ids: string[] }) {
  if (ids.length === 0) return null;
  return (
    <p className="text-text-secondary mt-3 text-sm">
      <span className="text-text-tertiary">{label} </span>
      {ids.map((id) => (
        <span
          key={id}
          className="border-border-strong text-text-secondary mr-1.5 inline-block rounded border px-1.5 py-0.5 font-mono text-xs"
        >
          {id}
        </span>
      ))}
    </p>
  );
}

function MetricRow({
  label,
  score,
  status,
}: {
  label: string;
  score: number | null;
  status: string | null;
}) {
  // null means not computed; a real 0.0 with status "complete" means
  // computed and genuinely zero. Both render from the pair, never the score
  // alone (see ../CLAUDE.md’s zero-vs-null rule).
  return (
    <div className="border-border grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-1.5 border-b py-2 last:border-b-0">
      <span className="text-text-secondary text-base">
        {label}
        <span className="text-text-tertiary ml-2 font-mono text-xs">
          {status ?? "no status recorded"}
        </span>
      </span>
      <span className="tabular-metric text-text-primary text-right text-base font-medium">
        {score === null ? "not scored" : score.toFixed(3)}
      </span>
      <span
        aria-hidden="true"
        className="bg-surface-high col-span-2 block h-1 overflow-hidden rounded-full"
      >
        {score !== null ? (
          <span
            className="bg-signal block h-full rounded-full"
            style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }}
          />
        ) : null}
      </span>
    </div>
  );
}

function FlashSection({ flash }: { flash: FlashJudgeView }) {
  return (
    <div>
      <MetricRow
        label="Faithfulness"
        score={flash.faithfulness_score}
        status={flash.faithfulness_status}
      />
      <MetricRow
        label="Answer relevance"
        score={flash.answer_relevance_score}
        status={flash.answer_relevance_status}
      />
      <MetricRow
        label="Context relevance"
        score={flash.context_relevance_score}
        status={flash.context_relevance_status}
      />
    </div>
  );
}

function FrontierSection({ evidence }: { evidence: FrontierEvidenceView }) {
  return (
    <div>
      <p className="text-text-tertiary font-mono text-xs">
        {evidence.judge_id} · verdict {evidence.verdict}
        {evidence.faithfulness_score !== null
          ? ` · faithfulness ${evidence.faithfulness_score.toFixed(3)}`
          : ""}
      </p>
      {evidence.rubric_reasoning ? (
        <blockquote className="border-disagreement text-text-primary mt-3 border-l-2 pl-4 text-base leading-relaxed">
          <p className="text-text-tertiary mb-1.5 text-sm">
            Frontier reasoning, as persisted
          </p>
          {evidence.rubric_reasoning}
        </blockquote>
      ) : null}
      <ChunkList
        label="Chunks it found supporting:"
        ids={evidence.cited_chunks_supporting}
      />
      <ChunkList
        label="Chunks it found contradicting:"
        ids={evidence.cited_chunks_contradicting}
      />
    </div>
  );
}

function JudgeBlock({
  title,
  note,
  dimmed = false,
  children,
}: {
  title: string;
  note?: string;
  dimmed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`border-border border-t pt-5 transition-opacity duration-[var(--dur-base)] ease-[var(--ease-soft)] ${dimmed ? "opacity-35" : "opacity-100"}`}
    >
      <h2 className="text-text-primary text-base font-semibold">{title}</h2>
      {note ? (
        <p className="text-text-tertiary mt-0.5 text-sm">{note}</p>
      ) : null}
      <div className="mt-3">{children}</div>
    </div>
  );
}

/** Both judge tiers for one execution, in reading order: the paired
 * disagreement when there is one, then the flash metrics, then the frontier
 * verdict with its persisted reasoning. */
export function JudgesColumn({
  detail,
  scores,
}: {
  detail: TraceDetailResponse;
  scores: DisagreementScores | null;
}) {
  const stoppedBefore = detail.rag_status !== "success";
  const [hovered, setHovered] = useState<Side | null>(null);
  const [pinned, setPinned] = useState<Side | null>(null);
  const side = scores ? (hovered ?? pinned) : null;
  return (
    <section
      aria-label={
        scores ? "Flash and frontier disagree" : "Judge verdicts for this trace"
      }
      className={
        scores
          ? "border-disagreement/40 bg-disagreement/[0.05] space-y-5 rounded-xl border p-5 sm:p-6"
          : "space-y-5"
      }
    >
      {scores ? (
        <DisagreementDuel
          scores={scores}
          side={side}
          onHover={setHovered}
          pinned={pinned}
          onPin={(s) => setPinned((p) => (p === s ? null : s))}
        />
      ) : null}

      <JudgeBlock
        title="Flash judge"
        note="Scores every delivered answer"
        dimmed={side === "frontier"}
      >
        {detail.flash ? (
          <FlashSection flash={detail.flash} />
        ) : (
          <p className="text-text-secondary text-base">
            {stoppedBefore
              ? "Nothing to judge: no answer was delivered."
              : "No flash verdict has been persisted for this execution."}
          </p>
        )}
      </JudgeBlock>

      <JudgeBlock
        title="Frontier judge"
        note="A second review on a sample"
        dimmed={side === "flash"}
      >
        {detail.frontier.evidence ? (
          <FrontierSection evidence={detail.frontier.evidence} />
        ) : (
          <p className="text-text-secondary text-base">
            {detail.frontier.note}
          </p>
        )}
      </JudgeBlock>
    </section>
  );
}
