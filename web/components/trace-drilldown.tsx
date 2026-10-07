"use client";

import { useEffect, useRef, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { CopyButton } from "@/components/copy-button";
import { ExecutionPath } from "@/components/execution-path";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { OutcomeBadge } from "@/components/outcome-badge";
import {
  DisagreementPanel,
  FlashSection,
  FrontierSection,
  Section,
  TechnicalRecord,
  detectDisagreement,
} from "@/components/trace-sections";
import { GATEWAY_URL } from "@/lib/config";
import { formatUtc } from "@/lib/format";
import type { TraceDetailResponse } from "@/lib/trace-api";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Keeps Tab and Shift+Tab inside the dialog, closes on Escape, locks page
 * scroll while open, and hands focus back to whatever opened it. */
function useDialogBehavior(
  dialogRef: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
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
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function TraceBody({ detail }: { detail: TraceDetailResponse }) {
  const disagreement = detectDisagreement(detail);
  const citedIds = new Set(detail.citations.map((c) => c.chunk_id));
  const stoppedBefore = detail.rag_status !== "success";

  return (
    <div className="space-y-8">
      {disagreement ? (
        <DisagreementPanel detail={detail} scores={disagreement} />
      ) : null}

      <section>
        <p className="eyebrow">Question</p>
        <h2 className="text-text-primary mt-2 text-2xl leading-snug font-semibold tracking-tight text-balance">
          {detail.query}
        </h2>
        <p className="text-text-tertiary mt-2 text-sm">
          {detail.ticker ?? "No ticker"}
          {detail.timestamp_utc ? ` · ${formatUtc(detail.timestamp_utc)}` : ""}
        </p>
      </section>

      <Section title="Execution path" id="trace-path">
        <ExecutionPath detail={detail} />
      </Section>

      <Section title="Retrieved evidence" id="trace-evidence">
        <p className="text-text-secondary text-base">
          {detail.retrieved_chunk_ids.length} chunk
          {detail.retrieved_chunk_ids.length === 1 ? "" : "s"} retrieved,{" "}
          {detail.citations.length} cited in the answer.
          {detail.retrieved_chunk_ids.length > 0 &&
          detail.citations.length === 0 &&
          !stoppedBefore
            ? " The model cited none of the retrieved context."
            : ""}
        </p>
        {detail.retrieved_chunk_ids.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {detail.retrieved_chunk_ids.map((id) => (
              <li
                key={id}
                className={`rounded border px-1.5 py-0.5 font-mono text-xs ${citedIds.has(id) ? "border-accent/50 text-accent" : "border-border-strong text-text-tertiary"}`}
              >
                {id}
                <span className="sr-only">
                  {citedIds.has(id) ? " (cited)" : " (not cited)"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-text-tertiary mt-2 text-sm">
            No retrieved chunk ids were recorded for this trace.
          </p>
        )}
        {detail.citations.length > 0 ? (
          <ul className="mt-4 space-y-3">
            {detail.citations.map((c, index) => (
              <li
                key={`${c.chunk_id}-${index}`}
                className="border-border-strong border-l-2 pl-4"
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

      <Section title="Delivered answer" id="trace-answer">
        {detail.answer ? (
          <p className="text-text-primary text-base leading-relaxed">
            {detail.answer}
          </p>
        ) : (
          <p className="text-text-secondary text-base">
            No answer was delivered.{" "}
            {detail.rag_status === "blocked"
              ? "The request was blocked, and the persisted record keeps the reason, not the model output."
              : detail.rag_status === "error"
                ? "The request ended in an error before an answer existed."
                : "No answer text is recorded."}
          </p>
        )}
      </Section>

      <Section title="Flash judge" id="trace-flash">
        {detail.flash ? (
          <FlashSection flash={detail.flash} />
        ) : (
          <p className="text-text-secondary text-base">
            {stoppedBefore
              ? "Nothing to judge: no answer was delivered."
              : "No flash verdict has been persisted for this execution."}
          </p>
        )}
      </Section>

      <Section title="Frontier judge" id="trace-frontier">
        {detail.frontier.evidence ? (
          <FrontierSection evidence={detail.frontier.evidence} />
        ) : (
          <p className="text-text-secondary text-base">
            {detail.frontier.note}
          </p>
        )}
      </Section>

      <Section title="Technical record" id="trace-technical">
        <TechnicalRecord detail={detail} />
      </Section>
    </div>
  );
}

/**
 * The trace detail drawer. A modal dialog: focus moves in, Tab stays
 * inside, Escape closes, and focus returns to the row that opened it.
 */
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

  useDialogBehavior(dialogRef, onClose);

  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/traces/${appTraceId}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(
            `Trace service unavailable. The gateway returned ${res.status}.`,
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
      className="fixed inset-0 z-50 flex justify-end overscroll-contain bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="border-border-strong bg-background-elevated flex h-full w-full max-w-3xl flex-col border-l outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-border bg-background-elevated/95 sticky top-0 z-10 border-b px-5 pt-4 pb-4 backdrop-blur sm:px-8">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="eyebrow">Trace</p>
              <div className="flex items-center">
                <p className="text-text-primary font-mono text-sm break-all">
                  {appTraceId}
                </p>
                <CopyButton value={appTraceId} label="Copy trace id" />
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium"
            >
              Close
              <kbd className="text-text-tertiary hidden font-mono text-xs sm:inline">
                Esc
              </kbd>
            </button>
          </div>
          {detail?.found ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <OutcomeBadge
                ragStatus={detail.rag_status ?? "unknown"}
                blockReason={detail.block_reason}
                blockRail={detail.block_rail}
                errorKind={detail.error_kind}
              />
              <JudgeStateBadge state={detail.judge_state} />
              {detail.frontier.sampled ? (
                <span className="border-signal/30 bg-signal/10 text-signal inline-flex rounded-md border px-2 py-0.5 text-xs font-medium">
                  Frontier sampled
                </span>
              ) : null}
            </div>
          ) : null}
        </header>

        <div className="thin-scroll flex-1 overflow-y-auto overscroll-contain px-5 py-8 sm:px-8">
          <AsyncState
            status={status}
            errorMessage={errorMessage}
            onRetry={() => {
              setStatus("loading");
              setRetryToken((n) => n + 1);
            }}
          >
            {!detail?.found ? (
              <p className="text-text-secondary text-base">
                {detail?.note ?? "Trace not found."}
              </p>
            ) : (
              <TraceBody detail={detail} />
            )}
          </AsyncState>
        </div>
      </div>
    </div>
  );
}
