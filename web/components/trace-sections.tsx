import type { ReactNode } from "react";
import type {
  FlashJudgeView,
  FrontierEvidenceView,
  TraceDetailResponse,
} from "@/lib/trace-api";

/** Mirrors _DISAGREEMENT_SCORE_DELTA in finsentry/dashboard/app.py: a
 * display threshold for highlighting, not re-derived independently. */
const DISAGREEMENT_SCORE_DELTA = 0.5;

export function detectDisagreement(
  detail: TraceDetailResponse,
): { flashScore: number; frontierScore: number } | null {
  const flashScore = detail.flash?.faithfulness_score;
  const frontierScore = detail.frontier.evidence?.faithfulness_score;
  if (flashScore == null || frontierScore == null) return null;
  if (Math.abs(flashScore - frontierScore) < DISAGREEMENT_SCORE_DELTA) {
    return null;
  }
  return { flashScore, frontierScore };
}

export function Section({
  title,
  children,
  id,
}: {
  title: string;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section aria-labelledby={id} className="border-border border-t pt-6">
      <h3 id={id} className="eyebrow">
        {title}
      </h3>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Two scores on one 0 to 1 axis, with the gap between them filled. The
 * distance is the finding, so it is drawn rather than only stated. */
function ScoreScale({ flash, frontier }: { flash: number; frontier: number }) {
  const lo = Math.min(flash, frontier) * 100;
  const hi = Math.max(flash, frontier) * 100;
  return (
    <div
      role="img"
      aria-label={`Faithfulness on a scale from 0 to 1: flash ${flash.toFixed(3)}, frontier ${frontier.toFixed(3)}.`}
      className="relative mx-2 mt-10 mb-8 h-2"
    >
      <div className="bg-surface-high absolute inset-0 rounded-full" />
      <div
        className="bg-disagreement/40 absolute inset-y-0"
        style={{ left: `${lo}%`, width: `${hi - lo}%` }}
      />
      {[
        { at: flash, name: "Flash", ring: "border-accent" },
        { at: frontier, name: "Frontier", ring: "border-disagreement" },
      ].map((m) => (
        <div
          key={m.name}
          className="absolute top-1/2"
          style={{ left: `${m.at * 100}%` }}
        >
          <span
            aria-hidden="true"
            className={`bg-background absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${m.ring}`}
          />
          <span className="text-text-secondary absolute top-3 -translate-x-1/2 text-xs whitespace-nowrap">
            {m.name}
          </span>
        </div>
      ))}
      <span className="text-text-tertiary absolute -top-6 -left-1 font-mono text-[11px]">
        0
      </span>
      <span className="text-text-tertiary absolute -top-6 -right-1 font-mono text-[11px]">
        1
      </span>
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

/** The showcase: where the two judge tiers split. Only persisted scores
 * and the frontier judge’s own written reasoning appear here. */
export function DisagreementPanel({
  detail,
  scores,
}: {
  detail: TraceDetailResponse;
  scores: { flashScore: number; frontierScore: number };
}) {
  const evidence = detail.frontier.evidence;
  return (
    <section
      aria-label="Flash and frontier disagree"
      className="border-disagreement/40 bg-disagreement/[0.06] rounded-xl border p-6"
    >
      <p className="text-disagreement text-sm font-semibold">
        The two judge tiers disagree on faithfulness
      </p>
      <div className="mt-5 grid grid-cols-2 gap-6">
        <div>
          <p className="eyebrow">Flash judge</p>
          <p className="tabular-metric text-text-primary mt-1 text-5xl font-semibold tracking-tight">
            {scores.flashScore.toFixed(3)}
          </p>
        </div>
        <div>
          <p className="eyebrow">Frontier, gemini-rubric</p>
          <p className="tabular-metric text-text-primary mt-1 text-5xl font-semibold tracking-tight">
            {scores.frontierScore.toFixed(3)}
          </p>
        </div>
      </div>
      <ScoreScale flash={scores.flashScore} frontier={scores.frontierScore} />
      {evidence?.rubric_reasoning ? (
        <blockquote className="border-disagreement text-text-primary border-l-2 pl-4 text-base leading-relaxed">
          <p className="eyebrow mb-1.5">Frontier reasoning, as persisted</p>
          {evidence.rubric_reasoning}
        </blockquote>
      ) : null}
      {evidence ? (
        <>
          <ChunkList
            label="Chunks it found supporting:"
            ids={evidence.cited_chunks_supporting}
          />
          <ChunkList
            label="Chunks it found contradicting:"
            ids={evidence.cited_chunks_contradicting}
          />
        </>
      ) : null}
    </section>
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
    <div className="border-border grid grid-cols-[1fr_auto] items-center gap-x-6 gap-y-2 border-b py-3 last:border-b-0 sm:grid-cols-[11rem_1fr_9rem]">
      <span className="text-text-secondary text-base">{label}</span>
      <span className="tabular-metric text-text-primary text-right text-base font-medium sm:order-3">
        {score === null ? "not scored" : score.toFixed(3)}
      </span>
      <span
        aria-hidden="true"
        className="bg-surface-high order-last col-span-2 block h-1.5 overflow-hidden rounded-full sm:order-2 sm:col-span-1"
      >
        {score !== null ? (
          <span
            className="bg-signal block h-full rounded-full"
            style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }}
          />
        ) : null}
      </span>
      <span className="text-text-tertiary col-span-2 font-mono text-xs sm:order-4 sm:col-span-3">
        {status ?? "no status recorded"}
      </span>
    </div>
  );
}

export function FlashSection({ flash }: { flash: FlashJudgeView }) {
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

export function FrontierSection({
  evidence,
}: {
  evidence: FrontierEvidenceView;
}) {
  return (
    <div className="space-y-3">
      <p className="text-text-tertiary font-mono text-xs">
        {evidence.judge_id} · verdict {evidence.verdict}
        {evidence.faithfulness_score !== null
          ? ` · faithfulness ${evidence.faithfulness_score.toFixed(3)}`
          : ""}
      </p>
      {evidence.rubric_reasoning ? (
        <p className="text-text-primary text-base leading-relaxed">
          {evidence.rubric_reasoning}
        </p>
      ) : null}
      <ChunkList label="Supporting:" ids={evidence.cited_chunks_supporting} />
      <ChunkList
        label="Contradicting:"
        ids={evidence.cited_chunks_contradicting}
      />
    </div>
  );
}

function Row({ k, v }: { k: string; v: string | null }) {
  return (
    <>
      <dt className="text-text-tertiary font-mono text-xs">{k}</dt>
      <dd className="text-text-secondary font-mono text-xs break-all">
        {v === null || v === "" ? "null" : v}
      </dd>
    </>
  );
}

/** Every persisted scalar on the trace, verbatim, so nothing a human label
 * summarized is out of reach. */
export function TechnicalRecord({ detail }: { detail: TraceDetailResponse }) {
  return (
    <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-2">
      <Row k="app_trace_id" v={detail.app_trace_id} />
      <Row k="timestamp_utc" v={detail.timestamp_utc} />
      <Row k="endpoint" v={detail.endpoint} />
      <Row k="rag_status" v={detail.rag_status} />
      <Row k="block_reason" v={detail.block_reason} />
      <Row k="block_rail" v={detail.block_rail} />
      <Row k="error_kind" v={detail.error_kind} />
      <Row k="error_detail" v={detail.error_detail} />
      <Row k="model_used" v={detail.model_used} />
      <Row k="confidence" v={detail.confidence} />
      <Row k="judge_state" v={detail.judge_state} />
      <Row k="retrieved chunks" v={String(detail.retrieved_chunk_ids.length)} />
      <Row k="citations" v={String(detail.citations.length)} />
    </dl>
  );
}
