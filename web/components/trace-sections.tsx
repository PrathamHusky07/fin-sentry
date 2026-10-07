import type { ReactNode } from "react";
import type { DisagreementScores } from "@/components/trace-judges";
import type { TraceDetailResponse } from "@/lib/trace-api";

/** Mirrors _DISAGREEMENT_SCORE_DELTA in finsentry/dashboard/app.py: a
 * display threshold for highlighting, not re-derived independently. */
const DISAGREEMENT_SCORE_DELTA = 0.5;

export function detectDisagreement(
  detail: TraceDetailResponse,
): DisagreementScores | null {
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
      <h3 id={id} className="text-text-primary text-base font-semibold">
        {title}
      </h3>
      <div className="mt-4">{children}</div>
    </section>
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
