import { ExecutionPath } from "@/components/execution-path";
import { JudgesColumn } from "@/components/trace-judges";
import {
  Section,
  TechnicalRecord,
  detectDisagreement,
} from "@/components/trace-sections";
import { formatUtc } from "@/lib/format";
import {
  BLOCK_STAGE_LABEL,
  blockReasonLabel,
  blockReasonMeaning,
  blockStage,
  errorKindLabel,
} from "@/lib/labels";
import type { TraceDetailResponse } from "@/lib/trace-api";

function Question({ detail }: { detail: TraceDetailResponse }) {
  return (
    <section aria-labelledby="trace-question">
      <h2 id="trace-question" className="text-text-tertiary text-sm">
        Question asked
      </h2>
      <p className="text-text-primary mt-1.5 text-xl leading-snug font-medium text-balance">
        {detail.query}
      </p>
      <p className="text-text-tertiary mt-2 text-sm">
        {detail.ticker ?? "No ticker"}
        {detail.timestamp_utc ? `, ${formatUtc(detail.timestamp_utc)}` : ""}
      </p>
    </section>
  );
}

/** Why there is no answer, in the persisted reason's own words. Never
 * invents answer text. */
function NoAnswer({ detail }: { detail: TraceDetailResponse }) {
  if (detail.rag_status === "blocked" && detail.block_reason) {
    const meaning = blockReasonMeaning(detail.block_reason);
    return (
      <div>
        <p className="text-text-primary text-lg font-medium">
          No answer was delivered.
        </p>
        <p className="text-warning mt-2 text-base">
          Stopped by the{" "}
          {BLOCK_STAGE_LABEL[blockStage(detail.block_reason)].toLowerCase()}:{" "}
          {blockReasonLabel(detail.block_reason, detail.block_rail)}
        </p>
        {meaning ? (
          <p className="text-text-secondary mt-2 text-base leading-relaxed">
            {meaning}
          </p>
        ) : null}
      </div>
    );
  }
  if (detail.rag_status === "error") {
    return (
      <div>
        <p className="text-text-primary text-lg font-medium">
          No answer was delivered.
        </p>
        <p className="text-failure mt-2 text-base">
          The request ended in an error
          {detail.error_kind ? `: ${errorKindLabel(detail.error_kind)}` : ""}
        </p>
        <p className="text-text-secondary mt-2 text-base leading-relaxed">
          A dependency failed before an answer existed.
        </p>
      </div>
    );
  }
  return (
    <p className="text-text-secondary text-base">
      No answer text is recorded for this execution.
    </p>
  );
}

/** The returned answer, verbatim: the largest thing in the drawer. Its
 * footer says how much of the retrieved context it cited. */
function Answer({
  detail,
  disputed,
}: {
  detail: TraceDetailResponse;
  disputed: boolean;
}) {
  return (
    <section
      aria-labelledby="trace-answer"
      className={`bg-surface rounded-xl border-l-4 p-5 sm:p-6 ${disputed ? "border-disagreement" : detail.answer ? "border-accent" : "border-border-strong"}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="trace-answer" className="text-text-tertiary text-sm">
          {detail.answer ? "Answer returned" : "Outcome"}
        </h2>
        {disputed ? (
          <p className="text-disagreement text-sm font-medium">
            The frontier judge disputes this answer
          </p>
        ) : null}
      </div>
      <div className="mt-3">
        {detail.answer ? (
          <p className="text-text-primary text-xl leading-relaxed whitespace-pre-line">
            {detail.answer}
          </p>
        ) : (
          <NoAnswer detail={detail} />
        )}
      </div>
      {detail.answer ? (
        <p className="text-text-tertiary mt-4 text-sm">
          {detail.model_used ? `Written by ${detail.model_used}. ` : ""}
          {detail.confidence ? `Stated confidence ${detail.confidence}. ` : ""}
          Cites {detail.citations.length} of {detail.retrieved_chunk_ids.length}{" "}
          retrieved chunk{detail.retrieved_chunk_ids.length === 1 ? "" : "s"}.
        </p>
      ) : null}
    </section>
  );
}

/** The retrieved chunks and what the answer made of them. A chunk is marked
 * cited when the answer cites it, and marked again when the frontier judge
 * named it as supporting or contradicting. */
function Evidence({ detail }: { detail: TraceDetailResponse }) {
  const cited = new Set(detail.citations.map((c) => c.chunk_id));
  const supporting = new Set(
    detail.frontier.evidence?.cited_chunks_supporting ?? [],
  );
  const contradicting = new Set(
    detail.frontier.evidence?.cited_chunks_contradicting ?? [],
  );
  const stoppedBefore = detail.rag_status !== "success";
  const retrieved = detail.retrieved_chunk_ids.length;

  return (
    <Section title="Evidence the answer rests on" id="trace-evidence">
      <p className="text-text-secondary text-base">
        {retrieved} chunk{retrieved === 1 ? "" : "s"} retrieved,{" "}
        {detail.citations.length} cited in the answer.
        {retrieved > 0 && detail.citations.length === 0 && !stoppedBefore
          ? " The model cited none of the retrieved context."
          : ""}
      </p>
      {retrieved > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {detail.retrieved_chunk_ids.map((id) => {
            const tags = [
              cited.has(id) ? "cited" : "not cited",
              supporting.has(id) ? "frontier: supports" : null,
              contradicting.has(id) ? "frontier: contradicts" : null,
            ].filter((t): t is string => t !== null);
            return (
              <li
                key={id}
                className={`rounded-md border px-2 py-1 ${cited.has(id) ? "border-accent/50 bg-accent/5" : "border-border-strong"}`}
              >
                <span
                  className={`font-mono text-xs ${cited.has(id) ? "text-accent" : "text-text-tertiary"}`}
                >
                  {id}
                </span>
                <span
                  className={`ml-2 text-xs ${contradicting.has(id) ? "text-disagreement" : "text-text-tertiary"}`}
                >
                  {tags.join(", ")}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-text-tertiary mt-2 text-sm">
          No retrieved chunk ids were recorded for this trace.
        </p>
      )}
      {detail.citations.length > 0 ? (
        <ul className="mt-5 space-y-4">
          {detail.citations.map((c, index) => (
            <li
              key={`${c.chunk_id}-${index}`}
              className="border-accent/40 border-l-2 pl-4"
            >
              <span className="text-accent font-mono text-xs">
                {c.chunk_id}
              </span>
              <p className="text-text-primary mt-1 text-base leading-relaxed">
                {c.quote}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

/**
 * One persisted execution laid out as a case file. The DOM order is the
 * reading order: question, the answer that was returned, the evidence it
 * rests on, the judges, the execution path, the technical record. From the
 * xl breakpoint the judges sit beside the answer and evidence, so the first
 * screen carries the answer and the verdict on it together without
 * changing that order.
 */
export function TraceCaseFile({ detail }: { detail: TraceDetailResponse }) {
  const scores = detectDisagreement(detail);
  return (
    <div className="grid gap-x-10 gap-y-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] xl:items-start">
      <div className="space-y-8">
        <Question detail={detail} />
        <Answer detail={detail} disputed={scores !== null} />
        <Evidence detail={detail} />
      </div>
      <JudgesColumn detail={detail} scores={scores} />
      <div className="xl:col-span-2">
        <Section title="Execution path" id="trace-path">
          <ExecutionPath detail={detail} />
        </Section>
      </div>
      <div className="xl:col-span-2">
        <Section title="Technical record" id="trace-technical">
          <TechnicalRecord detail={detail} />
        </Section>
      </div>
    </div>
  );
}
