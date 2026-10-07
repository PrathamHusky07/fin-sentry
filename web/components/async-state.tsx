import type { ReactNode } from "react";

export type AsyncStatus = "loading" | "error" | "ready";

/**
 * Shared loading and error rendering for a client-side fetch, with a real
 * Retry control and the actual failure reason, never a single swallowed
 * "could not be loaded" sentence. The caller owns the "ready" content,
 * including its own empty-result message, since what counts as empty
 * differs per surface.
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
    return (
      <div role="status" className="space-y-3" aria-label={loadingLabel}>
        <div className="bg-surface h-5 w-2/3 rounded motion-safe:animate-pulse" />
        <div className="bg-surface h-5 w-1/2 rounded motion-safe:animate-pulse" />
        <div className="bg-surface h-24 w-full rounded motion-safe:animate-pulse" />
        <span className="sr-only">{loadingLabel}</span>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div
        role="alert"
        className="border-failure/40 bg-failure/5 flex flex-wrap items-center gap-4 rounded-lg border p-5"
      >
        <p className="text-text-primary text-base">{errorMessage}</p>
        <button
          type="button"
          onClick={onRetry}
          className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-sm font-medium"
        >
          Retry
        </button>
      </div>
    );
  }
  return <>{children}</>;
}
