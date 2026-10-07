export type StatusColor =
  | "positive"
  | "warning"
  | "failure"
  | "info"
  | "accent"
  | "signal"
  | "disagreement"
  | "neutral";

const COLOR_CLASS: Record<StatusColor, string> = {
  positive: "bg-positive",
  warning: "bg-warning",
  failure: "bg-failure",
  info: "bg-info",
  accent: "bg-accent",
  signal: "bg-signal",
  disagreement: "bg-disagreement",
  neutral: "bg-text-tertiary",
};

/** A small colored status indicator. It is still unless `live` is set:
 * motion would imply liveness, and liveness is only ever claimed by the SSE
 * connection state on Live Operations, which says it in words as well. */
export function StatusDot({
  color,
  live = false,
}: {
  color: StatusColor;
  live?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${COLOR_CLASS[color]} ${live ? "pulse-live" : ""}`}
    />
  );
}
