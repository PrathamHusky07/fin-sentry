import { outcomeLabel, outcomeTone, type OutcomeTone } from "@/lib/labels";

const TONE_STYLE: Record<OutcomeTone, string> = {
  positive: "text-text-secondary border-border-strong",
  warning: "bg-warning/10 text-warning border-warning/30",
  failure: "bg-failure/10 text-failure border-failure/30",
  neutral: "text-text-secondary border-border-strong",
};

/** The request outcome in plain words: "Delivered", "Blocked · Malformed
 * JSON", "Error · Downstream unavailable". Delivered is deliberately quiet
 * because it is the normal case and should not compete with exceptions. */
export function OutcomeBadge({
  ragStatus,
  blockReason,
  blockRail,
  errorKind,
}: {
  ragStatus: string;
  blockReason: string | null;
  blockRail?: string | null;
  errorKind?: string | null;
}) {
  return (
    <span
      className={`inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE_STYLE[outcomeTone(ragStatus)]}`}
    >
      {outcomeLabel(ragStatus, blockReason, blockRail, errorKind)}
    </span>
  );
}
