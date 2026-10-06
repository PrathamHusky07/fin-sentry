"use client";

import { useEffect, useRef, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { ExecutionPath } from "@/components/execution-path";
import { StatusDot } from "@/components/status-dot";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceDetailResponse } from "@/lib/trace-api";

// Mirrors _DISAGREEMENT_SCORE_DELTA in finsentry/dashboard/app.py -- a
// display threshold for highlighting, not re-derived independently.
const DISAGREEMENT_SCORE_DELTA = 0.5;

function detectDisagreement(
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

interface ScoreRowProps {
  label: string;
  score: number | null;
  status: string | null;
}

function ScoreRow({ label, score, status }: ScoreRowProps) {
  // score=null with status "complete" never happens in practice (see
  // ../CLAUDE.md's zero-vs-null rule) -- null means not computed, a real
  // 0.0 with status="complete" means computed and genuinely zero. Both are
  // rendered from the score/status pair together, never the score alone.
  return (
    <div className="flex items-baseline justify-between border-b border-dashed py-1.5 last:border-b-0">
      <span className="text-text-secondary text-sm">{label}</span>
      <span className="flex items-baseline gap-2">
        <span className="tabular-metric text-text-primary text-sm font-medium">
          {score === null ? "—" : score.toFixed(3)}
        </span>
        <span className="text-text-secondary text-xs">
          {status ?? "no status recorded"}
        </span>
      </span>
    </div>
  );
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Keeps Tab/Shift+Tab inside the dialog -- a real focus trap, not a
 * cosmetic one. */
function useFocusTrap(
  dialogRef: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusables =
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export function TraceDrilldown({
  appTraceId,
  onClose,
}: {
  appTraceId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<TraceDetailResponse | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);

  useFocusTrap(dialogRef, onClose);

  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/traces/${appTraceId}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(
            `Trace service unavailable — gateway returned ${res.status}`,
          );
        }
        return res.json() as Promise<TraceDetailResponse>;
      })
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setStatus("ready");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setErrorMessage(
            err instanceof Error ? err.message : "Trace service unreachable.",
          );
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [appTraceId, retryToken]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Trace detail"
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="border-border bg-background-elevated w-full max-w-3xl rounded-md border p-6 outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-text-secondary text-xs break-all">
              {appTraceId}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary min-h-11 min-w-11 shrink-0 rounded-md text-sm"
          >
            Close
          </button>
        </div>

        <div className="mt-4">
          <AsyncState
            status={status}
            errorMessage={errorMessage}
            onRetry={() => {
              setStatus("loading");
              setRetryToken((n) => n + 1);
            }}
          >
            {!detail?.found ? (
              <p className="text-text-secondary text-sm">
                {detail?.note ?? "Trace not found."}
              </p>
            ) : (
              <div className="space-y-5">
                {(() => {
                  const disagreement = detectDisagreement(detail);
                  if (!disagreement) return null;
                  return (
                    <section
                      aria-label="Flash and frontier disagree"
                      className="border-disagreement/40 bg-disagreement/5 rounded-md border p-3.5"
                    >
                      <div className="flex items-center gap-2">
                        <StatusDot color="disagreement" />
                        <span className="text-disagreement text-sm font-semibold">
                          Flash and frontier disagree on faithfulness
                        </span>
                      </div>
                      <div className="mt-3 flex items-center gap-6">
                        <div>
                          <p className="text-text-secondary text-[11px] tracking-wide uppercase">
                            Flash
                          </p>
                          <p className="tabular-metric text-text-primary text-3xl font-semibold">
                            {disagreement.flashScore.toFixed(3)}
                          </p>
                        </div>
                        <span className="text-text-secondary text-xl">vs</span>
                        <div>
                          <p className="text-text-secondary text-[11px] tracking-wide uppercase">
                            Frontier (gemini-rubric)
                          </p>
                          <p className="tabular-metric text-text-primary text-3xl font-semibold">
                            {disagreement.frontierScore.toFixed(3)}
                          </p>
                        </div>
                      </div>
                      {detail.frontier.evidence?.rubric_reasoning ? (
                        <p className="text-text-primary mt-3 text-sm leading-relaxed">
                          {detail.frontier.evidence.rubric_reasoning}
                        </p>
                      ) : null}
                    </section>
                  );
                })()}

                <section>
                  <h2 className="text-text-primary text-lg font-semibold">
                    {detail.query}
                  </h2>
                  <p className="text-text-secondary mt-1 text-xs">
                    {detail.ticker ?? "no ticker"} · {detail.rag_status}
                    {detail.block_reason
                      ? ` · blocked: ${detail.block_reason} (${detail.block_rail})`
                      : ""}
                    {detail.error_kind ? ` · error: ${detail.error_kind}` : ""}
                    {detail.timestamp_utc
                      ? ` · ${new Date(detail.timestamp_utc).toLocaleString()}`
                      : ""}
                  </p>
                </section>

                <section>
                  <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                    Execution path
                  </h3>
                  <div className="mt-2">
                    <ExecutionPath detail={detail} />
                  </div>
                </section>

                <section>
                  <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                    Cited chunks
                  </h3>
                  <p className="text-text-secondary mt-1 text-xs">
                    {detail.retrieved_chunk_ids.length} chunk
                    {detail.retrieved_chunk_ids.length === 1 ? "" : "s"}{" "}
                    retrieved, {detail.citations.length} cited in the answer.
                    {detail.retrieved_chunk_ids.length > 0 &&
                    detail.citations.length === 0
                      ? " The model cited none of the retrieved context."
                      : ""}
                  </p>
                  {detail.citations.length > 0 ? (
                    <ul className="mt-2 space-y-2">
                      {detail.citations.map((c, index) => (
                        <li
                          key={`${c.chunk_id}-${index}`}
                          className="border-border rounded border p-2 text-xs"
                        >
                          <span className="text-text-secondary">
                            {c.chunk_id}
                          </span>
                          <p className="text-text-primary mt-1">{c.quote}</p>
                        </li>
                      ))}
                    </ul>
                  ) : detail.retrieved_chunk_ids.length === 0 ? (
                    <p className="text-text-secondary mt-1 text-sm">
                      No retrieved evidence recorded for this trace.
                    </p>
                  ) : null}
                </section>

                <section>
                  <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                    Answer
                  </h3>
                  {detail.answer ? (
                    <p className="text-text-primary mt-1 text-sm">
                      {detail.answer}
                    </p>
                  ) : (
                    <p className="text-text-secondary mt-1 text-sm">
                      No answer generated for this trace.
                    </p>
                  )}
                </section>

                <section>
                  <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                    Flash-tier RAGAS scores
                  </h3>
                  {detail.flash ? (
                    <div className="mt-1">
                      <ScoreRow
                        label="Faithfulness"
                        score={detail.flash.faithfulness_score}
                        status={detail.flash.faithfulness_status}
                      />
                      <ScoreRow
                        label="Answer relevance"
                        score={detail.flash.answer_relevance_score}
                        status={detail.flash.answer_relevance_status}
                      />
                      <ScoreRow
                        label="Context relevance"
                        score={detail.flash.context_relevance_score}
                        status={detail.flash.context_relevance_status}
                      />
                    </div>
                  ) : (
                    <p className="text-text-secondary mt-1 text-sm">
                      {detail.rag_status === "success"
                        ? "Not yet evaluated."
                        : "Blocked before evaluation -- nothing to judge."}
                    </p>
                  )}
                </section>

                <section>
                  <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                    Frontier evidence
                  </h3>
                  {detail.frontier.evidence ? (
                    <div className="mt-1 space-y-2 text-sm">
                      <p className="text-text-secondary text-xs">
                        {detail.frontier.evidence.judge_id} · verdict:{" "}
                        {detail.frontier.evidence.verdict}
                        {detail.frontier.evidence.faithfulness_score !== null
                          ? ` · score ${detail.frontier.evidence.faithfulness_score.toFixed(2)}`
                          : ""}
                      </p>
                      <p className="text-text-primary">
                        {detail.frontier.evidence.rubric_reasoning}
                      </p>
                      {detail.frontier.evidence.cited_chunks_supporting.length >
                      0 ? (
                        <p className="text-text-secondary text-xs">
                          Supporting:{" "}
                          {detail.frontier.evidence.cited_chunks_supporting.join(
                            ", ",
                          )}
                        </p>
                      ) : null}
                      {detail.frontier.evidence.cited_chunks_contradicting
                        .length > 0 ? (
                        <p className="text-text-secondary text-xs">
                          Contradicting:{" "}
                          {detail.frontier.evidence.cited_chunks_contradicting.join(
                            ", ",
                          )}
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <p className="text-text-secondary mt-1 text-sm">
                      {detail.frontier.note}
                    </p>
                  )}
                </section>
              </div>
            )}
          </AsyncState>
        </div>
      </div>
    </div>
  );
}
