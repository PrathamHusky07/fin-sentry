"use client";

import {
  DiagramScope,
  NodeDetailStrip,
  useDiagramModel,
  useNodeEvents,
  useNodeState,
  type NodeDetail,
} from "@/components/arch/node-model";
import { ArchLegend, LaneOutline } from "@/components/arch/svg-parts";
import {
  NODES,
  REQUEST_PATH,
  stageAnchor,
  type NodeId,
} from "@/lib/architecture-data";
import { LAYERS } from "@/lib/architecture-layers";
import { useHash } from "@/lib/use-hash";

interface Stage {
  id: NodeId;
  name: string;
  sub: string;
  /** What the stage contains, top to bottom. */
  drawer: { heading?: string; items: { text: string; note?: string }[] };
  /** Draws the drawer items as a connected sequence instead of a stack. */
  sequence?: boolean;
}

const STAGES: Stage[] = [
  {
    id: "client",
    name: "Client",
    sub: "a question about a filing",
    drawer: {
      items: [{ text: "One of ten SEC filers", note: "10-K, 10-Q and 8-K" }],
    },
  },
  {
    id: "gateway",
    name: "Gateway",
    sub: "the single front door",
    drawer: {
      items: [
        { text: "Owns the request", note: "from arrival to response" },
        { text: "Emits one event", note: "when the decision is made" },
      ],
    },
  },
  {
    id: "input",
    name: "Input rails",
    sub: "NeMo Guardrails",
    drawer: {
      heading: "Three checks. A failing rail blocks.",
      items: [
        { text: "Prompt injection", note: "Prompt Guard 2" },
        { text: "PII", note: "Presidio redacts" },
        { text: "Hazard taxonomy", note: "Llama Guard 3" },
      ],
    },
  },
  {
    id: "retrieval",
    name: "Retrieval",
    sub: "evidence from the filings",
    sequence: true,
    drawer: {
      heading: "A bad chunk is dropped. None left is a block.",
      items: [
        { text: "Query" },
        { text: "Vector search", note: "pgvector" },
        { text: "Chunk checks", note: "source trust, injection, PII" },
        { text: "Surviving evidence" },
      ],
    },
  },
  {
    id: "generation",
    name: "Generation",
    sub: "one bounded call",
    drawer: {
      items: [
        { text: "Local model", note: "llama3.1:8b" },
        { text: "20 s budget", note: "15 s per attempt" },
        {
          text: "Circuit breaker",
          note: "opens after five failures, for 30 s",
        },
      ],
    },
  },
  {
    id: "output",
    name: "Output rails",
    sub: "checks before it is returned",
    drawer: {
      heading: "Schema and phrases fail closed. Faithfulness fails open.",
      items: [
        { text: "Schema and citations" },
        { text: "Regulated phrases" },
        { text: "Faithfulness", note: "blocks below 0.7" },
      ],
    },
  },
  {
    id: "response",
    name: "Response",
    sub: "an answer or a named block",
    drawer: {
      heading: "The decision is made here.",
      items: [
        { text: "One event is published", note: "nobody waits for it" },
        { text: "Evaluation starts after this line" },
      ],
    },
  },
];

const EDGES: [string, string][] = REQUEST_PATH.slice(1).map((id, i) => [
  REQUEST_PATH[i],
  id,
]);

const DETAILS: Record<string, NodeDetail> = Object.fromEntries(
  STAGES.map((stage) => [
    stage.id,
    {
      title: NODES[stage.id].label,
      text: `${NODES[stage.id].summary} ${NODES[stage.id].why}`,
    },
  ]),
);

/** The dashed line where the decision is made and synchronous work ends. It
 * is the one asynchronous hand-off on this diagram, so the legend lights it. */
function DecisionLine() {
  const model = useDiagramModel();
  const lit = model?.kind === "async";
  return (
    <span
      aria-hidden="true"
      className={`border-signal/60 absolute top-0 -bottom-2 left-[calc((100%-4.5rem)*6/7+4.125rem)] border-l border-dashed transition-[opacity,box-shadow,border-color] duration-[var(--dur-base)] ${lit ? "border-signal border-l-2 shadow-[0_0_14px_var(--glow-signal)]" : ""} ${model?.kind === "sync" ? "opacity-30" : ""}`}
    />
  );
}

function Station({ stage }: { stage: Stage }) {
  const state = useNodeState(stage.id);
  const events = useNodeEvents(stage.id);
  const lit = state === "active";
  const anchor = stageAnchor(stage.id);
  const targeted = useHash() === anchor;
  return (
    <li
      id={anchor}
      data-state={state}
      className={`relative flex flex-col items-center text-center transition-opacity duration-[var(--dur-base)] ease-[var(--ease-soft)] ${state === "dim" ? "opacity-35" : "opacity-100"}`}
    >
      <button
        type="button"
        {...events}
        className="flex min-h-11 w-full flex-col items-center rounded-lg outline-offset-4"
      >
        <span
          aria-hidden="true"
          className={`border-accent relative z-10 h-5 w-5 rounded-full border-[3px] transition-[background-color,transform] duration-[var(--dur-base)] ease-[var(--ease)] ${lit || targeted ? "bg-accent scale-125 shadow-[0_0_18px_var(--glow-accent)]" : "bg-background"}`}
        />
        <span className="text-text-primary mt-3 text-[15px] font-semibold">
          {stage.name}
        </span>
        <span className="text-text-secondary mt-0.5 min-h-10 text-[13px] leading-snug">
          {stage.sub}
        </span>
      </button>
      <span
        aria-hidden="true"
        className={`h-4 w-px transition-colors duration-[var(--dur-base)] ${lit ? "bg-accent" : "bg-border-strong"}`}
      />
      <div
        className={`w-full flex-1 rounded-lg border p-3 text-left transition-colors duration-[var(--dur-base)] ${lit || targeted ? "border-accent/60 bg-surface" : state === "related" ? "border-accent/30 bg-surface/80" : "border-border bg-surface/60"}`}
      >
        {stage.drawer.heading ? (
          <p className="text-text-tertiary mb-2 text-xs leading-snug">
            {stage.drawer.heading}
          </p>
        ) : null}
        <ul
          className={
            stage.sequence
              ? "border-border-strong ml-1 space-y-2.5 border-l pl-3"
              : "space-y-2.5"
          }
        >
          {stage.drawer.items.map((item) => (
            <li key={item.text} className="relative">
              {stage.sequence ? (
                <span
                  aria-hidden="true"
                  className="bg-accent/70 absolute top-1.5 -left-[1.1rem] h-1.5 w-1.5 rounded-full"
                />
              ) : null}
              <p className="text-text-primary text-[13px] leading-snug font-medium">
                {item.text}
              </p>
              {item.note ? (
                <p className="text-text-secondary text-xs leading-snug">
                  {item.note}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </li>
  );
}

/** The solid rail, drawn as one bar and six segments. A segment lights when
 * it touches the active station, so the hand-offs read as part of the node. */
function Rail() {
  const model = useDiagramModel();
  const active = model?.active
    ? REQUEST_PATH.indexOf(model.active as NodeId)
    : -1;
  return (
    <>
      <span
        aria-hidden="true"
        className={`bg-accent absolute top-[9px] right-[calc(100%/14)] left-[calc(100%/14)] h-[3px] transition-opacity duration-[var(--dur-base)] ${active >= 0 ? "opacity-30" : "opacity-100"}`}
      />
      {REQUEST_PATH.slice(1).map((id, j) => (
        <span
          key={id}
          aria-hidden="true"
          className={`bg-accent absolute top-[8px] h-[5px] transition-opacity duration-[var(--dur-base)] ${active === j || active === j + 1 ? "opacity-100 shadow-[0_0_14px_var(--glow-accent)]" : "opacity-0"}`}
          style={{
            left: `calc(100% * ${(j + 0.5) / 7})`,
            width: `calc(100% / 7)`,
          }}
        />
      ))}
    </>
  );
}

/**
 * Diagram 1, the request path, drawn as a pipeline. Seven stations sit on
 * one solid rail because every hand-off is synchronous. Each station opens
 * a drawer underneath with what it really contains, so the three input
 * checks, the retrieval sequence, the call bounds and the output rails are
 * visible without a click. A dashed line marks where the decision is made
 * and synchronous work ends. Stations join the shared node model: the
 * active station lights the rail segments that touch it.
 */
export function RequestPipeline() {
  return (
    <div>
      <DiagramScope edges={EDGES} details={DETAILS}>
        <div className="hidden lg:block">
          <p className="text-accent flex items-center gap-3 text-sm font-medium">
            The user waits for everything on this rail
            <span aria-hidden="true" className="bg-accent/40 h-px flex-1" />
          </p>
          <ol
            aria-label="The request path, left to right"
            className="relative mt-5 grid grid-cols-7 gap-x-3"
          >
            <Rail />
            <DecisionLine />
            {STAGES.map((stage) => (
              <Station key={stage.id} stage={stage} />
            ))}
          </ol>
          <NodeDetailStrip />
          <ArchLegend items={["sync", "async"]} />
        </div>
      </DiagramScope>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[0].outline} />
      </div>
    </div>
  );
}
