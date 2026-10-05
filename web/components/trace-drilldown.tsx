"use client";

import { useEffect, useState } from "react";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceDetailResponse } from "@/lib/trace-api";

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

export function TraceDrilldown({
  appTraceId,
  onClose,
}: {
  appTraceId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<TraceDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/traces/${appTraceId}`)
      .then((res) =>
        res.ok ? (res.json() as Promise<TraceDetailResponse>) : null,
      )
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [appTraceId]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Trace detail"
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        className="border-border bg-background-elevated w-full max-w-2xl rounded-md border p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-text-primary text-sm font-semibold break-all">
            {appTraceId}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary min-h-11 min-w-11 shrink-0 rounded-md text-sm"
          >
            Close
          </button>
        </div>

        {loading ? (
          <p className="text-text-secondary mt-4 text-sm">Loading…</p>
        ) : null}

        {!loading && (!detail || !detail.found) ? (
          <p className="text-text-secondary mt-4 text-sm">
            {detail?.note ?? "This trace could not be loaded."}
          </p>
        ) : null}

        {!loading && detail?.found ? (
          <div className="mt-4 space-y-5">
            <section>
              <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                Request
              </h3>
              <p className="text-text-primary mt-1 text-sm">{detail.query}</p>
              <p className="text-text-secondary mt-1 text-xs">
                {detail.ticker ?? "no ticker"} · {detail.rag_status}
                {detail.block_reason
                  ? ` · blocked: ${detail.block_reason} (${detail.block_rail})`
                  : ""}
                {detail.error_kind ? ` · error: ${detail.error_kind}` : ""}
              </p>
            </section>

            {detail.citations.length > 0 ? (
              <section>
                <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                  Retrieved chunks
                </h3>
                <ul className="mt-1 space-y-2">
                  {detail.citations.map((c) => (
                    <li
                      key={c.chunk_id}
                      className="border-border rounded border p-2 text-xs"
                    >
                      <span className="text-text-secondary">{c.chunk_id}</span>
                      <p className="text-text-primary mt-1">{c.quote}</p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {detail.answer ? (
              <section>
                <h3 className="text-text-secondary text-xs tracking-wide uppercase">
                  Answer
                </h3>
                <p className="text-text-primary mt-1 text-sm">
                  {detail.answer}
                </p>
              </section>
            ) : null}

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
                  {detail.frontier.evidence.cited_chunks_contradicting.length >
                  0 ? (
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
        ) : null}
      </div>
    </div>
  );
}
