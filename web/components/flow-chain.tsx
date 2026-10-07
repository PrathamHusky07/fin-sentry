import { Fragment } from "react";

export type ChainTone =
  "request" | "stream" | "evaluation" | "evidence" | "muted";

export interface ChainStep {
  label: string;
  sub?: string;
  /** Concrete checks or sub-parts shown under the node’s name. */
  chips?: string[];
  tone: ChainTone;
  /** Draws the node with a dashed outline: not per request, or not built. */
  dashed?: boolean;
}

const TONE_BORDER: Record<ChainTone, string> = {
  request: "border-accent/45",
  stream: "border-border-strong",
  evaluation: "border-signal/45",
  evidence: "border-text-tertiary/50",
  muted: "border-border-strong",
};

const TONE_DOT: Record<ChainTone, string> = {
  request: "bg-accent",
  stream: "bg-text-secondary",
  evaluation: "bg-signal",
  evidence: "bg-text-secondary",
  muted: "bg-text-tertiary",
};

/**
 * A left-to-right chain of stages that turns into a vertical chain on small
 * screens. `edge` says how the stages hand off: solid for a synchronous
 * call, dashed for an asynchronous hand-off, the same encoding the landing
 * topology uses.
 */
export function FlowChain({
  steps,
  edge,
  label,
}: {
  steps: ChainStep[];
  edge: "sync" | "async";
  label: string;
}) {
  const stroke = edge === "sync" ? "var(--accent)" : "var(--signal)";
  return (
    <ol
      aria-label={label}
      className="flex flex-col lg:flex-row lg:items-stretch"
    >
      {steps.map((step, i) => (
        <Fragment key={step.label}>
          <li className="min-w-0 lg:flex-1">
            <div
              className={`bg-surface h-full rounded-lg border p-4 ${TONE_BORDER[step.tone]} ${step.dashed ? "border-dashed" : ""}`}
            >
              <div className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[step.tone]}`}
                />
                <span className="text-text-primary text-base font-semibold">
                  {step.label}
                </span>
              </div>
              {step.sub ? (
                <p className="text-text-secondary mt-1.5 text-sm leading-snug">
                  {step.sub}
                </p>
              ) : null}
              {step.chips && step.chips.length > 0 ? (
                <ul className="border-border mt-3 flex flex-col gap-1.5 border-t pt-3">
                  {step.chips.map((chip) => (
                    <li
                      key={chip}
                      className="text-text-secondary text-[13px] leading-snug"
                    >
                      {chip}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
          {i < steps.length - 1 ? (
            <li
              aria-hidden="true"
              className="flex items-center justify-center py-1 lg:px-0.5 lg:py-0"
            >
              <svg
                viewBox="0 0 24 28"
                className="h-7 w-6 shrink-0 lg:hidden"
                fill="none"
              >
                <path
                  d="M12 0V20"
                  stroke={stroke}
                  strokeWidth="1.5"
                  strokeDasharray={edge === "async" ? "4 4" : undefined}
                />
                <path d="M6 18l6 7 6-7" stroke={stroke} strokeWidth="1.5" />
              </svg>
              <svg
                viewBox="0 0 28 24"
                className="hidden h-6 w-7 shrink-0 lg:block"
                fill="none"
              >
                <path
                  d="M0 12H20"
                  stroke={stroke}
                  strokeWidth="1.5"
                  strokeDasharray={edge === "async" ? "4 4" : undefined}
                />
                <path d="M18 6l7 6-7 6" stroke={stroke} strokeWidth="1.5" />
              </svg>
            </li>
          ) : null}
        </Fragment>
      ))}
    </ol>
  );
}
