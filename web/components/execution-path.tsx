"use client";

import { Fragment, useState } from "react";
import {
  BLOCK_STAGE_LABEL,
  blockReasonLabel,
  blockReasonMeaning,
  blockStage,
  errorKindLabel,
} from "@/lib/labels";
import type { TraceDetailResponse } from "@/lib/trace-api";

type StageStatus =
  | "passed"
  | "partial"
  | "blocked"
  | "error"
  | "not_reached"
  | "pending"
  | "unknown";

type StageKey = "input" | "retrieval" | "generation" | "output" | "unknown";

interface Stage {
  label: string;
  status: StageStatus;
  /** Human-readable outcome. */
  summary: string;
  /** The persisted machine fields behind the outcome, for the engineer. */
  code?: string;
  /** The persisted reason or evidence behind the outcome, shown when the
   * stage is opened. Only ever built from fields on the trace. */
  detail?: string;
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
  // Partial is a measured result with a gap, not a stop: it gets the info
  // hue and a half-filled dot so it never reads as blocked.
  partial: {
    dot: "border-info bg-info/35",
    text: "text-info",
    word: "Partial",
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
  unknown: {
    dot: "bg-transparent border-text-secondary border-dotted",
    text: "text-text-secondary",
    word: "Unknown",
  },
};

// error_kind values the gateway emits on the generation call
// (finsentry/gateway/main.py). Anything else is unclassified, never
// assumed to be generation.
const GENERATION_ERROR_KINDS = new Set([
  "downstream_unavailable",
  "downstream_rate_limit",
  "downstream_error",
]);

function errorStage(kind: string | null): StageKey {
  if (kind === "input_rail_service_unavailable") return "input";
  if (kind === "vector_search_failed") return "retrieval";
  if (kind && GENERATION_ERROR_KINDS.has(kind)) return "generation";
  return "unknown";
}

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
  const errorAt = errored ? errorStage(errorKind) : null;
  const code = codeFor(detail);
  const delivered = detail.rag_status === "success";
  const chunks = detail.retrieved_chunk_ids.length;

  const stopped = (stage: StageKey) => at === stage || errorAt === stage;
  const unclassified = stopped("unknown");
  const reachedRetrieval = !stopped("input");
  const reachedGeneration = reachedRetrieval && !stopped("retrieval");
  const reachedOutput = reachedGeneration && !stopped("generation");

  function outcome(
    stage: Exclude<StageKey, "unknown">,
    reached: boolean,
    passedText: string,
    passedDetail?: string,
  ): Pick<Stage, "status" | "summary" | "code" | "detail"> {
    if (unclassified) {
      return {
        status: "unknown",
        summary: "Not determined: the stage that stopped it is unclassified",
      };
    }
    if (at === stage && detail.block_reason) {
      return {
        status: "blocked",
        summary: blockReasonLabel(detail.block_reason, detail.block_rail),
        code,
        detail: blockReasonMeaning(detail.block_reason) ?? undefined,
      };
    }
    if (errorAt === stage) {
      return {
        status: "error",
        summary: errorKind ? errorKindLabel(errorKind) : "Failed",
        code,
        detail: `The request ended in an error at this stage. The persisted error kind is ${errorKind ?? "not recorded"}.`,
      };
    }
    if (!reached) return { status: "not_reached", summary: "Not reached" };
    return { status: "passed", summary: passedText, detail: passedDetail };
  }

  const flash = detail.flash;
  const frontier = detail.frontier;

  const unknownStage: Stage[] = unclassified
    ? [
        {
          label: BLOCK_STAGE_LABEL.unknown,
          status: at === "unknown" ? "blocked" : "error",
          summary:
            at === "unknown" && detail.block_reason
              ? `${blockReasonLabel(detail.block_reason, detail.block_rail)}, a reason not mapped to a stage`
              : `${errorKind ? errorKindLabel(errorKind) : "Failed"}, an error not mapped to a stage`,
          code,
        },
      ]
    : [];

  return [
    {
      label: "Request",
      status: "passed",
      summary: "Received by the gateway",
      detail: detail.endpoint
        ? `Endpoint ${detail.endpoint}${detail.ticker ? `, ticker ${detail.ticker}` : ""}.`
        : undefined,
    },
    ...unknownStage,
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
        chunks > 0
          ? `Retrieved ${detail.retrieved_chunk_ids.slice(0, 8).join(", ")}${chunks > 8 ? ` and ${chunks - 8} more` : ""}.`
          : undefined,
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
        detail.model_used
          ? `Model ${detail.model_used}${detail.confidence ? `, stated confidence ${detail.confidence}` : ""}.`
          : undefined,
      ),
    },
    {
      label: BLOCK_STAGE_LABEL.output,
      ...outcome(
        "output",
        reachedOutput,
        "Answer passed every output rail",
        detail.citations.length > 0
          ? `The answer cites ${new Set(detail.citations.map((c) => c.chunk_id)).size} distinct retrieved chunks.`
          : undefined,
      ),
    },
    {
      label: "Flash judge",
      async: true,
      status: flash
        ? flash.status === "complete"
          ? "passed"
          : flash.status === "partial"
            ? "partial"
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
      detail: flash
        ? `Status ${flash.status}. Faithfulness ${flash.faithfulness_score?.toFixed(3) ?? "not scored"}, answer relevance ${flash.answer_relevance_score?.toFixed(3) ?? "not scored"}, context relevance ${flash.context_relevance_score?.toFixed(3) ?? "not scored"}.`
        : undefined,
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
      detail: frontier.evidence
        ? `Verdict ${frontier.evidence.verdict}${frontier.evidence.faithfulness_score !== null ? `, faithfulness ${frontier.evidence.faithfulness_score.toFixed(3)}` : ""}.`
        : frontier.note || undefined,
    },
  ];
}

/** The real per-trace execution path. Every stage’s outcome traces to a
 * field on TraceDetailResponse, and the raw codes sit under the plain
 * summary for the engineer who needs them. A stage with persisted evidence
 * behind it opens on hover, focus or tap to show it. */
export function ExecutionPath({ detail }: { detail: TraceDetailResponse }) {
  const stages = buildStages(detail);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  return (
    <ol className="relative">
      {stages.map((stage, i) => {
        const style = STATUS_STYLE[stage.status];
        const showBoundary = stage.async && !stages[i - 1]?.async;
        const expandable = Boolean(stage.detail);
        const open = hovered === stage.label || pinned === stage.label;
        const heading = (
          <span className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-text-primary text-base font-medium">
              {stage.label}
            </span>
            <span className={`text-sm ${style.text}`}>
              <span className="sr-only">{style.word}: </span>
              {stage.summary}
            </span>
          </span>
        );
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
            <li
              className="relative pb-5 pl-8 last:pb-0"
              onPointerEnter={(e) => {
                if (e.pointerType === "mouse") setHovered(stage.label);
              }}
              onPointerLeave={(e) => {
                if (e.pointerType === "mouse") setHovered(null);
              }}
            >
              {i < stages.length - 1 ? (
                <span
                  aria-hidden="true"
                  className="bg-border-strong absolute top-3 bottom-0 left-[5px] w-px"
                />
              ) : null}
              <span
                aria-hidden="true"
                className={`absolute top-[5px] left-0 h-[11px] w-[11px] rounded-full border-2 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${style.dot} ${open ? "scale-125" : ""}`}
              />
              {expandable ? (
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() =>
                    setPinned((p) => (p === stage.label ? null : stage.label))
                  }
                  className="min-h-6 w-full rounded-md text-left"
                >
                  {heading}
                </button>
              ) : (
                heading
              )}
              {stage.code ? (
                <p className="text-text-tertiary mt-1 font-mono text-xs break-words">
                  {stage.code}
                </p>
              ) : null}
              {expandable ? (
                <div
                  className={`grid transition-[grid-template-rows,opacity] duration-[var(--dur-base)] ease-[var(--ease)] ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}
                >
                  <p
                    inert={!open}
                    className="text-text-secondary overflow-hidden text-sm leading-relaxed"
                  >
                    <span className="block pt-1.5">{stage.detail}</span>
                  </p>
                </div>
              ) : null}
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}
