import { Fragment } from "react";
import {
  BLOCK_STAGE_LABEL,
  blockReasonLabel,
  blockStage,
  errorKindLabel,
} from "@/lib/labels";
import type { TraceDetailResponse } from "@/lib/trace-api";

type StageStatus = "passed" | "blocked" | "error" | "not_reached" | "pending";

interface Stage {
  label: string;
  status: StageStatus;
  /** Human-readable outcome. */
  summary: string;
  /** The persisted machine fields behind the outcome, for the engineer. */
  code?: string;
  /** True for the stages that run after the response, off the request path. */
  async?: boolean;
}

const STATUS_STYLE: Record<
  StageStatus,
  { dot: string; text: string; word: string }
> = {
  passed: {
    dot: "bg-positive border-positive",
    text: "text-text-primary",
    word: "Passed",
  },
  blocked: {
    dot: "bg-warning border-warning",
    text: "text-warning",
    word: "Blocked",
  },
  error: {
    dot: "bg-failure border-failure",
    text: "text-failure",
    word: "Error",
  },
  not_reached: {
    dot: "bg-transparent border-text-tertiary border-dashed",
    text: "text-text-tertiary",
    word: "Not reached",
  },
  pending: {
    dot: "bg-transparent border-text-secondary border-dashed",
    text: "text-text-secondary",
    word: "Pending",
  },
};

function codeFor(detail: TraceDetailResponse): string {
  const parts: string[] = [];
  if (detail.block_reason) parts.push(`block_reason=${detail.block_reason}`);
  if (detail.block_rail) parts.push(`block_rail=${detail.block_rail}`);
  if (detail.error_kind) parts.push(`error_kind=${detail.error_kind}`);
  return parts.join(" · ");
}

/**
 * Which stage each persisted outcome belongs to. A block is placed by its
 * block_reason (see lib/labels.ts, verified against the gateway source). An
 * input_rail_blocked can be prompt injection, the hazard taxonomy or a
 * failing input rail, so the stage is named from block_rail, never assumed
 * to be injection. An error is placed by error_kind.
 */
export function buildStages(detail: TraceDetailResponse): Stage[] {
  const blocked = detail.rag_status === "blocked" && detail.block_reason;
  const errored = detail.rag_status === "error";
  const at = blocked ? blockStage(detail.block_reason as string) : null;
  const errorKind = detail.error_kind;
  const errorAt =
    errorKind === "input_rail_service_unavailable"
      ? "input"
      : errorKind === "vector_search_failed"
        ? "retrieval"
        : errored
          ? "generation"
          : null;
  const code = codeFor(detail);
  const delivered = detail.rag_status === "success";
  const chunks = detail.retrieved_chunk_ids.length;

  const stopped = (stage: "input" | "retrieval" | "generation" | "output") =>
    at === stage || errorAt === stage;
  const reachedRetrieval = !stopped("input");
  const reachedGeneration = reachedRetrieval && !stopped("retrieval");
  const reachedOutput = reachedGeneration && !stopped("generation");

  function outcome(
    stage: "input" | "retrieval" | "generation" | "output",
    reached: boolean,
    passedText: string,
  ): Pick<Stage, "status" | "summary" | "code"> {
    if (at === stage && detail.block_reason) {
      return {
        status: "blocked",
        summary: blockReasonLabel(detail.block_reason, detail.block_rail),
        code,
      };
    }
    if (errorAt === stage) {
      return {
        status: "error",
        summary: errorKind ? errorKindLabel(errorKind) : "Failed",
        code,
      };
    }
    if (!reached) return { status: "not_reached", summary: "Not reached" };
    return { status: "passed", summary: passedText };
  }

  const flash = detail.flash;
  const frontier = detail.frontier;

  return [
    { label: "Request", status: "passed", summary: "Received by the gateway" },
    {
      label: BLOCK_STAGE_LABEL.input,
      ...outcome("input", true, "No input rail stopped it"),
    },
    {
      label: BLOCK_STAGE_LABEL.retrieval,
      ...outcome(
        "retrieval",
        reachedRetrieval,
        chunks > 0
          ? `${chunks} chunk${chunks === 1 ? "" : "s"} retrieved`
          : "No chunk ids were recorded",
      ),
    },
    {
      label: "Generation",
      ...outcome(
        "generation",
        reachedGeneration,
        detail.model_used
          ? `Answered by ${detail.model_used}`
          : "Model not recorded",
      ),
    },
    {
      label: BLOCK_STAGE_LABEL.output,
      ...outcome("output", reachedOutput, "Answer passed every output rail"),
    },
    {
      label: "Flash judge",
      async: true,
      status: flash
        ? flash.status === "complete"
          ? "passed"
          : "blocked"
        : delivered
          ? "pending"
          : "not_reached",
      summary: flash
        ? flash.status === "complete"
          ? "All three metrics scored"
          : flash.status === "partial"
            ? "Partial: some metrics were skipped"
            : "The judge scored none of the metrics"
        : delivered
          ? "No verdict has been persisted"
          : "Nothing to judge: no answer was delivered",
    },
    {
      label: "Frontier judge",
      async: true,
      status: frontier.evidence
        ? "passed"
        : frontier.sampled
          ? "pending"
          : "not_reached",
      summary: frontier.evidence
        ? `Reviewed by ${frontier.evidence.judge_id}`
        : frontier.sampled
          ? "Sampled, but no real judge evidence is persisted"
          : "Not in the one-in-ten sample",
    },
  ];
}

/** The real per-trace execution path. Every stage’s outcome traces to a
 * field on TraceDetailResponse, and the raw codes sit under the plain
 * summary for the engineer who needs them. */
export function ExecutionPath({ detail }: { detail: TraceDetailResponse }) {
  const stages = buildStages(detail);
  return (
    <ol className="relative">
      {stages.map((stage, i) => {
        const style = STATUS_STYLE[stage.status];
        const showBoundary = stage.async && !stages[i - 1]?.async;
        return (
          <Fragment key={stage.label}>
            {showBoundary ? (
              <li role="presentation" className="relative pb-4 pl-8">
                <span
                  aria-hidden="true"
                  className="bg-border-strong absolute inset-y-0 left-[5px] w-px"
                />
                <p className="eyebrow border-border border-t border-dashed pt-3">
                  Off the request path, asynchronous
                </p>
              </li>
            ) : null}
            <li className="relative pb-5 pl-8 last:pb-0">
              {i < stages.length - 1 ? (
                <span
                  aria-hidden="true"
                  className="bg-border-strong absolute top-3 bottom-0 left-[5px] w-px"
                />
              ) : null}
              <span
                aria-hidden="true"
                className={`absolute top-[5px] left-0 h-[11px] w-[11px] rounded-full border-2 ${style.dot}`}
              />
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="text-text-primary text-base font-medium">
                  {stage.label}
                </span>
                <span className={`text-sm ${style.text}`}>
                  <span className="sr-only">{style.word}: </span>
                  {stage.summary}
                </span>
              </div>
              {stage.code ? (
                <p className="text-text-tertiary mt-1 font-mono text-xs break-words">
                  {stage.code}
                </p>
              ) : null}
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}
