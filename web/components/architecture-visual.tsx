type StageKind = "core" | "rail" | "judge";

interface ArchStage {
  label: string;
  detail: string;
  kind: StageKind;
}

const STAGES: ArchStage[] = [
  { label: "Request", detail: "Incoming RAG query", kind: "core" },
  {
    label: "Input rails",
    detail: "Injection, PII, content safety",
    kind: "rail",
  },
  {
    label: "Retrieval",
    detail: "Chunk-level trust and PII checks",
    kind: "rail",
  },
  { label: "Generation", detail: "Downstream model response", kind: "core" },
  {
    label: "Output rails",
    detail: "Schema, faithfulness, phrasing",
    kind: "rail",
  },
  {
    label: "Flash judge",
    detail: "Gemini 2.5 Flash, every response",
    kind: "judge",
  },
  {
    label: "Frontier judge",
    detail: "Sampled rubric-scored review",
    kind: "judge",
  },
  {
    label: "Calibration",
    detail: "Judges checked against humans",
    kind: "judge",
  },
  {
    label: "Investigation",
    detail: "Every trace stays inspectable",
    kind: "core",
  },
];

const KIND_BORDER: Record<StageKind, string> = {
  core: "border-accent/50",
  rail: "border-info/50",
  judge: "border-positive/50",
};

const KIND_DOT: Record<StageKind, string> = {
  core: "bg-accent",
  rail: "bg-info",
  judge: "bg-positive",
};

/**
 * The real Fin-Sentry architecture, structurally identical to the
 * operations tool's reliability-pipeline component (same nine stages, same
 * module layout) but built as its own component: this one carries no live
 * counts (the presentation layer shows structure, not telemetry) and uses
 * a larger, more deliberate visual treatment appropriate to a landing
 * hero. Motion is purely decorative flow -- a traveling highlight along
 * the connector -- and is disabled under prefers-reduced-motion via the
 * motion-safe: variant, never implying live request traffic.
 */
export function ArchitectureVisual() {
  return (
    <div
      role="img"
      aria-label="Fin-Sentry architecture: a request passes through input rails, retrieval, generation, and output rails, then is scored by a flash judge on every response and a sampled frontier judge, both checked against human calibration, with every trace available for investigation."
      className="w-full"
    >
      <ol className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-stretch sm:gap-0">
        {STAGES.map((stage, i) => (
          <li key={stage.label} className="flex items-stretch sm:flex-1">
            <div
              className={`bg-background-elevated flex min-w-0 flex-1 flex-col gap-1 rounded-lg border p-3.5 ${KIND_BORDER[stage.kind]}`}
            >
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className={`h-1.5 w-1.5 rounded-full ${KIND_DOT[stage.kind]}`}
                />
                <span className="text-text-primary text-sm font-semibold">
                  {stage.label}
                </span>
              </span>
              <span className="text-text-secondary text-xs leading-snug">
                {stage.detail}
              </span>
            </div>
            {i < STAGES.length - 1 ? (
              <div
                aria-hidden="true"
                className="hidden w-5 shrink-0 items-center self-center sm:flex"
              >
                <div className="pipeline-connector h-0.5 w-full rounded-full" />
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
