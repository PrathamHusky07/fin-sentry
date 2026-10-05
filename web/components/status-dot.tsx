type StatusColor = "positive" | "warning" | "failure" | "info" | "neutral";

const COLOR_CLASS: Record<StatusColor, string> = {
  positive: "bg-positive",
  warning: "bg-warning",
  failure: "bg-failure",
  info: "bg-info",
  neutral: "bg-text-secondary",
};

/** A small colored status indicator -- the one way this app signals
 * healthy/degraded/failed/informational/unknown state at a glance. */
export function StatusDot({ color }: { color: StatusColor }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-2 w-2 rounded-full ${COLOR_CLASS[color]}`}
    />
  );
}
