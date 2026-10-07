import type { EdgeKind, NodeId, Plane } from "@/lib/architecture-data";

/**
 * Hand-placed coordinates for the landing topology, in a 1200 x 756
 * viewBox. The request path runs left to right across the top. The event
 * stream is a horizontal bus beneath it, so evaluation reads as consumers
 * hanging off a log rather than as another step in the request. The
 * evidence plane sits at the bottom and is fed by the verdicts and by the
 * stream itself.
 */
export const VIEW_W = 1200;
export const VIEW_H = 756;
export const NODE_W = 136;
export const NODE_H = 84;

export interface NodeBox {
  cx: number;
  cy: number;
  w: number;
  h: number;
  /** Lines of sub-label text drawn under the node’s name. */
  lines: string[];
}

export const BOX: Record<NodeId, NodeBox> = {
  client: {
    cx: 90,
    cy: 142,
    w: NODE_W,
    h: NODE_H,
    lines: ["POST /v1/rag/query"],
  },
  gateway: { cx: 255, cy: 142, w: NODE_W, h: NODE_H, lines: ["FastAPI"] },
  input: { cx: 420, cy: 142, w: NODE_W, h: NODE_H, lines: ["NeMo Guardrails"] },
  retrieval: {
    cx: 585,
    cy: 142,
    w: NODE_W,
    h: NODE_H,
    lines: ["pgvector + rail"],
  },
  generation: {
    cx: 750,
    cy: 142,
    w: NODE_W,
    h: NODE_H,
    lines: ["Ollama, local"],
  },
  output: {
    cx: 915,
    cy: 142,
    w: NODE_W,
    h: NODE_H,
    lines: ["schema, phrases,", "faithfulness"],
  },
  response: {
    cx: 1080,
    cy: 142,
    w: NODE_W,
    h: NODE_H,
    lines: ["answer or", "named block"],
  },
  stream: {
    cx: 685,
    cy: 288,
    w: 990,
    h: 52,
    lines: ["Redpanda: rag-responses, judge-verdicts, rag-frontier-verdicts"],
  },
  flash: {
    cx: 330,
    cy: 472,
    w: NODE_W,
    h: NODE_H,
    lines: ["gemini-3.6-flash,", "hosted"],
  },
  sampler: {
    cx: 560,
    cy: 472,
    w: NODE_W,
    h: NODE_H,
    lines: ["sha256(trace id)", "mod 10"],
  },
  frontier: {
    cx: 770,
    cy: 472,
    w: NODE_W,
    h: NODE_H,
    lines: ["gemini-rubric,", "hosted"],
  },
  calibration: {
    cx: 1010,
    cy: 472,
    w: NODE_W,
    h: NODE_H,
    lines: ["Cohen’s kappa,", "global"],
  },
  store: {
    cx: 550,
    cy: 668,
    w: 160,
    h: NODE_H,
    lines: ["sources +", "materialized views"],
  },
  investigation: {
    cx: 800,
    cy: 668,
    w: NODE_W,
    h: NODE_H,
    lines: ["one row per", "execution"],
  },
  mcp: { cx: 1010, cy: 668, w: NODE_W, h: NODE_H, lines: ["five read tools"] },
};

export interface PlaneBand {
  plane: Plane;
  y: number;
  h: number;
  title: string;
  timing: string;
}

export const BANDS: PlaneBand[] = [
  {
    plane: "request",
    y: 14,
    h: 200,
    title: "REQUEST PATH",
    timing: "synchronous",
  },
  {
    plane: "evaluation",
    y: 346,
    h: 220,
    title: "EVALUATION PLANE",
    timing: "asynchronous",
  },
  { plane: "evidence", y: 590, h: 150, title: "EVIDENCE", timing: "persisted" },
];

/** SVG path per edge, keyed "from>to". Elbows are explicit so connectors
 * never cross a node. */
export const EDGE_PATH: Record<string, string> = {
  "client>gateway": "M158,142 H187",
  "gateway>input": "M323,142 H352",
  "input>retrieval": "M488,142 H517",
  "retrieval>generation": "M653,142 H682",
  "generation>output": "M818,142 H847",
  "output>response": "M983,142 H1012",
  "gateway>stream": "M255,184 V262",
  "stream>flash": "M330,314 V430",
  "stream>sampler": "M560,314 V430",
  "sampler>frontier": "M628,472 H702",
  "calibration>frontier": "M942,472 H838",
  "flash>store": "M330,514 V574 H515 V626",
  "frontier>store": "M770,514 V574 H585 V626",
  "stream>store": "M212,314 V668 H470",
  "store>investigation": "M630,668 H732",
  "store>mcp": "M550,710 V732 H1010 V710",
};

export function edgeKey(from: NodeId, to: NodeId): string {
  return `${from}>${to}`;
}

export const EDGE_STYLE: Record<
  EdgeKind,
  { stroke: string; width: number; dash?: string }
> = {
  sync: { stroke: "var(--accent)", width: 1.75 },
  async: { stroke: "var(--signal)", width: 1.5 },
  measure: { stroke: "var(--text-secondary)", width: 1.25, dash: "2 5" },
};

export const PLANE_STROKE: Record<Plane, string> = {
  request: "var(--accent)",
  stream: "var(--text-secondary)",
  evaluation: "var(--signal)",
  evidence: "var(--text-secondary)",
};
