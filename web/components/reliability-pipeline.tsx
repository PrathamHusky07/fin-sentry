import { Panel } from "@/components/panel";

type StageKind = "core" | "rail" | "judge";

interface Stage {
  label: string;
  kind: StageKind;
  detail: string;
  sublabel?: string;
  blockedCount?: number;
  expanded?: string;
}

const KIND_ACCENT: Record<StageKind, string> = {
  core: "border-l-accent",
  rail: "border-l-info",
  judge: "border-l-positive",
};

const KIND_LABEL: Record<StageKind, string> = {
  core: "Request path",
  rail: "Guardrail",
  judge: "Judge",
};

/**
 * The real Fin-Sentry execution path, read directly off the module layout
 * (finsentry/rails/input, finsentry/rails/retrieval, finsentry/rails/output,
 * finsentry/judges/flash_judge.py, finsentry/consumer/frontier_consumer.py,
 * the Day 6 calibration harness) -- an architecture diagram, not live
 * telemetry. Counts shown are real, all-time, derived from persisted
 * fields (see docs/internal/day9-frontend-data-contract.md); the diagram
 * shape itself does not change with traffic. Each stage is focusable and
 * reveals a second line of real detail on hover/focus -- a static
 * structural fact (which checks a rail runs, which judge evaluates), never
 * a live value appearing only on interaction.
 */
export function ReliabilityPipeline({
  blockedByReason,
  flashCompleteCount,
  flashPartialCount,
  flashNeverRanCount,
  frontierSampledCount,
}: {
  blockedByReason: { reason: string; count: number }[];
  flashCompleteCount: number;
  flashPartialCount: number;
  flashNeverRanCount: number;
  frontierSampledCount: number;
}) {
  const byReason = (reason: string) =>
    blockedByReason.find((r) => r.reason === reason)?.count ?? 0;
  const inputRailBlocked = byReason("input_rail_blocked");
  const retrievalBlocked = byReason("no_trustworthy_sources");
  const malformedJson = byReason("malformed_json");
  const schemaViolation = byReason("schema_violation");
  const hallucinatedCitation = byReason("hallucinated_citation");
  const lowFaithfulness = byReason("low_faithfulness");
  const outputBlocked =
    malformedJson + schemaViolation + hallucinatedCitation + lowFaithfulness;

  const stages: Stage[] = [
    {
      label: "Request",
      kind: "core",
      detail: "Incoming RAG query",
    },
    {
      label: "Input rails",
      kind: "rail",
      detail: "Prompt injection, PII, content safety",
      sublabel: `${inputRailBlocked} blocked`,
      blockedCount: inputRailBlocked,
      expanded:
        "Llama Prompt Guard 2, Presidio, Llama Guard 3 (hazard taxonomy)",
    },
    {
      label: "Retrieval rail",
      kind: "rail",
      detail: "Chunk-level injection, trust, PII",
      sublabel: `${retrievalBlocked} blocked`,
      blockedCount: retrievalBlocked,
      expanded:
        "Indirect-injection scan, source-trust policy, per-chunk PII check",
    },
    {
      label: "RAG generation",
      kind: "core",
      detail: "Downstream model response",
      expanded: "Ollama llama3.1:8b, OpenAI-compatible endpoint",
    },
    {
      label: "Output rails",
      kind: "rail",
      detail: "Schema, faithfulness, regulated phrases",
      sublabel: `${outputBlocked} blocked`,
      blockedCount: outputBlocked,
      expanded: `malformed_json ${malformedJson} · schema_violation ${schemaViolation} · hallucinated_citation ${hallucinatedCitation} · low_faithfulness ${lowFaithfulness}`,
    },
    {
      label: "Flash evaluation",
      kind: "judge",
      detail: "Gemini 2.5 Flash, 3 RAGAS metrics",
      sublabel: `${flashCompleteCount} complete, ${flashPartialCount} partial`,
      expanded: `${flashNeverRanCount} not yet evaluated · judge-pipeline-error state exists but is unused in today's data`,
    },
    {
      label: "Frontier evaluation",
      kind: "judge",
      detail: "Sampled gemini-rubric judge",
      sublabel: `${frontierSampledCount} sampled`,
      expanded:
        "~10% deterministic sampling hash, real gemini-rubric evidence only",
    },
    {
      label: "Calibration",
      kind: "judge",
      detail: "Weekly κ vs. human labels",
      expanded: "Cohen's kappa against the human-labeled financial golden set",
    },
  ];

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-text-primary text-sm font-semibold">
          Reliability pipeline
        </h2>
        <span className="text-text-secondary text-[11px] tracking-wide uppercase">
          Static architecture -- counts are real, all-time totals, not a live
          feed
        </span>
      </div>
      <ol className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch sm:gap-0">
        {stages.map((stage, i) => (
          <li key={stage.label} className="flex items-stretch sm:flex-1">
            <div
              tabIndex={0}
              className={`group border-border bg-surface focus-visible:outline-accent relative flex min-w-0 flex-1 flex-col gap-0.5 rounded-md border border-l-2 p-2.5 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${KIND_ACCENT[stage.kind]} ${
                stage.blockedCount && stage.blockedCount > 0
                  ? "ring-warning/30 ring-1"
                  : ""
              }`}
            >
              <span className="text-text-secondary text-[9px] font-medium tracking-wide uppercase">
                {KIND_LABEL[stage.kind]}
              </span>
              <span className="text-text-primary text-xs font-medium">
                {stage.label}
              </span>
              <span className="text-text-secondary text-[11px] leading-snug">
                {stage.detail}
              </span>
              {stage.sublabel ? (
                <span
                  className={`tabular-metric mt-1 text-[11px] ${
                    stage.blockedCount && stage.blockedCount > 0
                      ? "text-warning font-medium"
                      : "text-text-secondary"
                  }`}
                >
                  {stage.sublabel}
                </span>
              ) : null}
              {stage.expanded ? (
                <span className="text-text-secondary bg-background-elevated border-border pointer-events-none absolute inset-x-0 top-full z-20 mt-1 hidden rounded-md border p-2 text-[11px] leading-snug shadow-sm group-focus-within:block group-hover:block">
                  {stage.expanded}
                </span>
              ) : null}
            </div>
            {i < stages.length - 1 ? (
              <div
                aria-hidden="true"
                className="flex shrink-0 items-center self-center sm:mx-1"
              >
                <div className="pipeline-connector hidden h-px w-3 sm:block" />
                <span className="text-text-secondary hidden text-xs sm:block">
                  ▸
                </span>
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
