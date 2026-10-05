import type { ReactNode } from "react";

export type AsyncStatus = "loading" | "error" | "ready";

/**
 * Shared loading/error rendering for a client-side fetch, with a real
 * Retry control and the actual failure reason -- never a single swallowed
 * "could not be loaded" sentence (see docs/build-log.md, Day 9 Phase 0).
 * The caller owns the "ready" content, including its own empty-result
 * message, since what counts as empty differs per surface.
 */
export function AsyncState({
  status,
  errorMessage,
  onRetry,
  loadingLabel = "Loading…",
  children,
}: {
  status: AsyncStatus;
  errorMessage: string | null;
  onRetry: () => void;
  loadingLabel?: string;
  children: ReactNode;
}) {
  if (status === "loading") {
    return <p className="text-text-secondary text-sm">{loadingLabel}</p>;
  }
  if (status === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-failure text-sm">{errorMessage}</p>
        <button
          type="button"
          onClick={onRetry}
          className="border-border hover:bg-surface min-h-11 rounded-md border px-3 text-sm"
        >
          Retry
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
