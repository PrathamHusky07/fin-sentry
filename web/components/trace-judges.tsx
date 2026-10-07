import type {
  FlashJudgeView,
  FrontierEvidenceView,
  TraceDetailResponse,
} from "@/lib/trace-api";

export interface DisagreementScores {
  flashScore: number;
  frontierScore: number;
}

/** Two scores on one 0 to 1 axis, with the gap between them filled. The
 * distance is the finding, so it is drawn and not only stated. */
function ScoreScale({ flash, frontier }: { flash: number; frontier: number }) {
  const lo = Math.min(flash, frontier) * 100;
  const hi = Math.max(flash, frontier) * 100;
  return (
    <div
      role="img"
      aria-label={`Faithfulness on a scale from 0 to 1: flash ${flash.toFixed(3)}, frontier ${frontier.toFixed(3)}.`}
      className="relative mx-3 mt-6 mb-9 h-2"
    >
      <div className="bg-surface-high absolute inset-0 rounded-full" />
      <div
        className="bg-disagreement/35 absolute inset-y-0"
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
 * faithfulness scores, large, with the distance between them drawn. */
function DisagreementDuel({ scores }: { scores: DisagreementScores }) {
  return (
    <div>
      <p className="text-disagreement text-base font-semibold">
        The two judge tiers disagree on faithfulness
      </p>
      <div className="mt-5 grid grid-cols-2 gap-6">
        <div>
          <p className="text-text-secondary text-sm">Flash judge</p>
          <p className="tabular-metric text-accent mt-1 text-5xl font-semibold tracking-tight">
            {scores.flashScore.toFixed(3)}
          </p>
        </div>
        <div>
          <p className="text-text-secondary text-sm">Frontier judge</p>
          <p className="tabular-metric text-disagreement mt-1 text-5xl font-semibold tracking-tight">
            {scores.frontierScore.toFixed(3)}
          </p>
        </div>
      </div>
      <ScoreScale flash={scores.flashScore} frontier={scores.frontierScore} />
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
    <div className="border-border grid grid-cols-[1fr_auto] items-center gap-x-6 gap-y-1.5 border-b py-2.5 last:border-b-0">
      <span className="text-text-secondary text-base">{label}</span>
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
      <span className="text-text-tertiary col-span-2 font-mono text-xs">
        {status ?? "no status recorded"}
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
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border-border border-t pt-5">
      <h3 className="text-text-primary text-base font-semibold">{title}</h3>
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
      {scores ? <DisagreementDuel scores={scores} /> : null}

      <JudgeBlock title="Flash judge" note="Scores every delivered answer">
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

      <JudgeBlock title="Frontier judge" note="A second review on a sample">
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
