import { LaneOutline } from "@/components/arch/svg-parts";
import { LAYERS } from "@/lib/architecture-layers";

interface Stage {
  name: string;
  sub: string;
  /** What the stage contains, top to bottom. */
  drawer: { heading?: string; items: { text: string; note?: string }[] };
  /** Draws the drawer items as a connected sequence instead of a stack. */
  sequence?: boolean;
}

const STAGES: Stage[] = [
  {
    name: "Client",
    sub: "a question about a filing",
    drawer: {
      items: [{ text: "One of ten SEC filers", note: "10-K, 10-Q and 8-K" }],
    },
  },
  {
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

/**
 * Diagram 1, the request path, drawn as a pipeline. Seven stations sit on
 * one solid rail because every hand-off is synchronous. Each station opens
 * a drawer underneath with what it really contains, so the three input
 * checks, the retrieval sequence, the call bounds and the output rails are
 * visible without a click. A dashed line marks where the decision is made
 * and synchronous work ends.
 */
export function RequestPipeline() {
  return (
    <div>
      <div className="hidden lg:block">
        <p className="text-accent flex items-center gap-3 text-sm font-medium">
          The user waits for everything on this rail
          <span aria-hidden="true" className="bg-accent/40 h-px flex-1" />
        </p>
        <ol
          aria-label="The request path, left to right"
          className="relative mt-5 grid grid-cols-7 gap-x-3"
        >
          <span
            aria-hidden="true"
            className="bg-accent absolute top-[9px] right-[calc(100%/14)] left-[calc(100%/14)] h-[3px]"
          />
          <span
            aria-hidden="true"
            className="border-signal/60 absolute top-0 -bottom-2 left-[calc((100%-4.5rem)*6/7+4.125rem)] border-l border-dashed"
          />
          {STAGES.map((stage) => (
            <li
              key={stage.name}
              className="group relative flex flex-col items-center text-center"
            >
              <span
                aria-hidden="true"
                className="bg-background border-accent group-hover:bg-accent relative z-10 h-5 w-5 rounded-full border-[3px] transition-colors group-hover:scale-125"
              />
              <p className="text-text-primary mt-3 text-[15px] font-semibold">
                {stage.name}
              </p>
              <p className="text-text-secondary mt-0.5 min-h-10 text-[13px] leading-snug">
                {stage.sub}
              </p>
              <span
                aria-hidden="true"
                className="bg-border-strong group-hover:bg-accent h-4 w-px transition-colors"
              />
              <div className="border-border group-hover:border-accent/60 bg-surface/60 group-hover:bg-surface w-full flex-1 rounded-lg border p-3 text-left transition-colors">
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
          ))}
        </ol>
      </div>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[0].outline} />
      </div>
    </div>
  );
}
