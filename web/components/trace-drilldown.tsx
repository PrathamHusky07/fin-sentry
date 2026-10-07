"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { CopyButton } from "@/components/copy-button";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import { OutcomeBadge } from "@/components/outcome-badge";
import { TraceCaseFile } from "@/components/trace-case-file";
import { detectDisagreement } from "@/components/trace-sections";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceDetailResponse } from "@/lib/trace-api";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Keeps Tab and Shift+Tab inside the dialog, closes on Escape, locks page
 * scroll while open, and hands focus back to whatever opened it. */
function useDialogBehavior(
  dialogRef: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
  active: boolean,
) {
  useEffect(() => {
    if (!active) return;
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
  }, [active]);
}

const noopSubscribe = () => () => {};

/** False during server render and hydration, true once on the client, so
 * the portal below only touches document.body in the browser. */
function useIsClient(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
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
  const scores = detail?.found ? detectDisagreement(detail) : null;

  const isClient = useIsClient();
  useDialogBehavior(dialogRef, onClose, isClient);

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

  // The drawer renders into document.body so no page-level stacking context
  // (the section backdrops isolate themselves) can sit above it or trap it
  // beneath the sticky navigation.
  if (!isClient) return null;
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Trace detail"
      className="swap-in fixed inset-0 z-50 flex justify-end overscroll-contain bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="modal-in border-line-active bg-background-elevated flex h-full w-full max-w-6xl origin-right flex-col border-l shadow-[-30px_0_60px_-30px_rgb(0_0_0/0.8)] outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-border bg-background-elevated/95 sticky top-0 z-10 border-b px-5 pt-4 pb-4 backdrop-blur sm:px-8">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-text-tertiary text-sm">Trace</p>
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
              {scores ? (
                <span className="border-disagreement/40 bg-disagreement/10 text-disagreement inline-flex rounded-md border px-2 py-0.5 text-xs font-medium">
                  Judges disagree: flash {scores.flashScore.toFixed(3)},
                  frontier {scores.frontierScore.toFixed(3)}
                </span>
              ) : null}
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
              <TraceCaseFile detail={detail} />
            )}
          </AsyncState>
        </div>
      </div>
    </div>,
    document.body,
  );
}
