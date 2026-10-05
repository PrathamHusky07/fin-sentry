import { Panel } from "@/components/panel";

interface Stage {
  label: string;
  detail: string;
  sublabel?: string;
}

/**
 * The real Fin-Sentry execution path, read directly off the module layout
 * (finsentry/rails/input, finsentry/rails/retrieval, finsentry/rails/output,
 * finsentry/judges/flash_judge.py, finsentry/consumer/frontier_consumer.py,
 * the Day 6 calibration harness) -- an architecture diagram, not live
 * telemetry. Counts shown are real, all-time, derived from persisted
 * fields (see docs/internal/day9-frontend-data-contract.md); the diagram
 * shape itself does not change with traffic.
 */
export function ReliabilityPipeline({
  blockedByReason,
  flashEvaluatedCount,
  flashNeverRanCount,
  frontierSampledCount,
}: {
  blockedByReason: { reason: string; count: number }[];
  flashEvaluatedCount: number;
  flashNeverRanCount: number;
  frontierSampledCount: number;
}) {
  const byReason = (reason: string) =>
    blockedByReason.find((r) => r.reason === reason)?.count ?? 0;
  const inputRailBlocked = byReason("input_rail_blocked");
  const retrievalBlocked = byReason("no_trustworthy_sources");
  const outputBlocked =
    byReason("malformed_json") +
    byReason("hallucinated_citation") +
    byReason("low_faithfulness");

  const stages: Stage[] = [
    { label: "Request", detail: "Incoming RAG query" },
    {
      label: "Input rails",
      detail: "Prompt injection, PII, content safety",
      sublabel:
        inputRailBlocked > 0 ? `${inputRailBlocked} blocked` : "0 blocked",
    },
    {
      label: "Retrieval rail",
      detail: "Chunk-level injection, trust, PII",
      sublabel:
        retrievalBlocked > 0 ? `${retrievalBlocked} blocked` : "0 blocked",
    },
    { label: "RAG generation", detail: "Downstream model response" },
    {
      label: "Output rails",
      detail: "Schema, faithfulness, regulated phrases",
      sublabel: outputBlocked > 0 ? `${outputBlocked} blocked` : "0 blocked",
    },
    {
      label: "Flash evaluation",
      detail: "Gemini 2.5 Flash, 3 RAGAS metrics",
      sublabel: `${flashEvaluatedCount} evaluated, ${flashNeverRanCount} not yet`,
    },
    {
      label: "Frontier evaluation",
      detail: "Sampled gemini-rubric judge",
      sublabel: `${frontierSampledCount} sampled`,
    },
    { label: "Calibration", detail: "Weekly κ vs. human labels" },
  ];

  return (
    <Panel className="p-4">
      <h2 className="text-text-primary text-sm font-semibold">
        Reliability pipeline
      </h2>
      <p className="text-text-secondary mt-1 text-xs">
        The real execution path. Counts are all-time totals, not a live feed.
      </p>
      <ol className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch sm:gap-0">
        {stages.map((stage, i) => (
          <li key={stage.label} className="flex items-stretch sm:flex-1">
            <div className="border-border bg-surface flex min-w-0 flex-1 flex-col gap-0.5 rounded-md border p-2.5">
              <span className="text-text-primary text-xs font-medium">
                {stage.label}
              </span>
              <span className="text-text-secondary text-[11px] leading-snug">
                {stage.detail}
              </span>
              {stage.sublabel ? (
                <span className="tabular-metric text-text-secondary mt-1 text-[11px]">
                  {stage.sublabel}
                </span>
              ) : null}
            </div>
            {i < stages.length - 1 ? (
              <div
                aria-hidden="true"
                className="pipeline-connector mx-1 hidden w-4 shrink-0 self-center sm:block"
              />
            ) : null}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
