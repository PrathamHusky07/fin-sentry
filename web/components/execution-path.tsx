import { StatusDot } from "@/components/status-dot";
import type { TraceDetailResponse } from "@/lib/trace-api";

type StageStatus = "passed" | "blocked" | "not_reached" | "info";

interface Stage {
  label: string;
  status: StageStatus;
  detail: string;
}

const STATUS_COLOR: Record<
  StageStatus,
  "positive" | "failure" | "neutral" | "info"
> = {
  passed: "positive",
  blocked: "failure",
  not_reached: "neutral",
  info: "info",
};

// Real block_rail values observed in persisted data (see
// docs/internal/day9-frontend-data-contract.md): which pipeline stage each
// one belongs to.
const INPUT_RAIL_NAMES = new Set(["check prompt injection"]);
const RETRIEVAL_RAIL_NAMES = new Set(["retrieval-rail"]);
const OUTPUT_RAIL_NAMES = new Set(["schema-enforcement", "faithfulness"]);

function buildStages(detail: TraceDetailResponse): Stage[] {
  const blockRail = detail.block_rail;
  const blockedAtInput = blockRail !== null && INPUT_RAIL_NAMES.has(blockRail);
  const blockedAtRetrieval =
    blockRail !== null && RETRIEVAL_RAIL_NAMES.has(blockRail);
  const blockedAtOutput =
    blockRail !== null && OUTPUT_RAIL_NAMES.has(blockRail);
  const blockedBeforeRetrieval =
    detail.rag_status === "blocked" && blockedAtInput;
  const reachedGeneration = detail.answer !== null && detail.answer !== "";

  return [
    { label: "Request", status: "passed", detail: "Received" },
    {
      label: "Input rails",
      status: blockedAtInput ? "blocked" : "passed",
      detail: blockedAtInput
        ? `Blocked: ${detail.block_reason ?? "input rail"}`
        : "Passed",
    },
    {
      label: "Retrieval",
      status: blockedBeforeRetrieval
        ? "not_reached"
        : blockedAtRetrieval
          ? "blocked"
          : detail.retrieved_chunk_ids.length > 0
            ? "passed"
            : "not_reached",
      detail: blockedBeforeRetrieval
        ? "Not reached"
        : blockedAtRetrieval
          ? `Blocked: ${detail.block_reason ?? "retrieval rail"}`
          : detail.retrieved_chunk_ids.length > 0
            ? `${detail.retrieved_chunk_ids.length} chunk${detail.retrieved_chunk_ids.length === 1 ? "" : "s"} retrieved`
            : "No chunks retrieved",
    },
    {
      label: "Generation",
      status: reachedGeneration ? "passed" : "not_reached",
      detail: reachedGeneration
        ? `Model: ${detail.model_used || "unknown"}`
        : "Not reached",
    },
    {
      label: "Output rails",
      status: blockedAtOutput
        ? "blocked"
        : reachedGeneration
          ? "passed"
          : "not_reached",
      detail: blockedAtOutput
        ? `Blocked: ${detail.block_reason ?? "output rail"}`
        : reachedGeneration
          ? "Passed"
          : "Not reached",
    },
    {
      label: "Flash evaluation",
      status: detail.flash ? "passed" : "info",
      detail: detail.flash ? detail.flash.status : "Not yet evaluated",
    },
    {
      label: "Frontier evaluation",
      status: detail.frontier.evidence ? "passed" : "info",
      detail: detail.frontier.evidence
        ? detail.frontier.evidence.verdict
        : detail.frontier.note,
    },
  ];
}

/** The real per-trace execution path -- every stage's outcome traces to a
 * field on TraceDetailResponse, nothing inferred beyond what's persisted. */
export function ExecutionPath({ detail }: { detail: TraceDetailResponse }) {
  const stages = buildStages(detail);
  return (
    <ol className="flex flex-col gap-1.5">
      {stages.map((stage) => (
        <li key={stage.label} className="flex items-center gap-2.5 text-sm">
          <StatusDot color={STATUS_COLOR[stage.status]} />
          <span className="text-text-primary w-32 shrink-0">{stage.label}</span>
          <span className="text-text-secondary min-w-0 flex-1 truncate text-xs">
            {stage.detail}
          </span>
        </li>
      ))}
    </ol>
  );
}
