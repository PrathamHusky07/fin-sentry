import { GENERATION_BOUNDS } from "@/lib/generation-bounds";

const { callBudgetSeconds, attemptCapSeconds, requestDeadlineSeconds } =
  GENERATION_BOUNDS;

const pct = (seconds: number) => `${(seconds / requestDeadlineSeconds) * 100}%`;

/**
 * The three time limits drawn as lengths on one scale. They are not a timeline of one request:
 * the model call starts after the input rails and retrieval, so the shorter bars are not drawn
 * at a position in the longer one. The figure carries the same numbers as the list under it.
 */
export function BoundsScale() {
  return (
    <figure
      className="border-line bg-background-elevated/60 rounded-xl border p-5 sm:p-6"
      aria-label={`Three limits on one scale: the whole request ${requestDeadlineSeconds} seconds, the model call ${callBudgetSeconds} seconds, one attempt ${attemptCapSeconds} seconds.`}
    >
      <div aria-hidden="true" className="space-y-4">
        <div>
          <p className="text-text-secondary text-base sm:text-sm">
            Whole request
            <span className="text-text-primary tabular-metric ml-2 font-medium">
              {requestDeadlineSeconds} s
            </span>
          </p>
          <div className="bg-surface-high mt-1.5 h-3 w-full rounded-sm" />
        </div>
        <div>
          <p className="text-text-secondary text-base sm:text-sm">
            Model call, all attempts
            <span className="text-signal tabular-metric ml-2 font-medium">
              {callBudgetSeconds} s
            </span>
          </p>
          <div className="mt-1.5 h-3 w-full">
            <div
              className="bg-signal/40 h-3 rounded-sm"
              style={{ width: pct(callBudgetSeconds) }}
            />
          </div>
        </div>
        <div>
          <p className="text-text-secondary text-base sm:text-sm">
            One attempt
            <span className="text-accent tabular-metric ml-2 font-medium">
              {attemptCapSeconds} s
            </span>
          </p>
          <div className="mt-1.5 h-3 w-full">
            <div
              className="bg-accent/60 h-3 rounded-sm"
              style={{ width: pct(attemptCapSeconds) }}
            />
          </div>
        </div>
      </div>
      <figcaption className="text-text-tertiary mt-4 text-base sm:text-sm">
        Lengths on one scale, not a timeline of one request.
      </figcaption>
    </figure>
  );
}
