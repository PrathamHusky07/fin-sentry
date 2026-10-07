import type { EdgeKind, NodeId, Plane } from "@/lib/architecture-data";

/**
 * Hand-placed coordinates for the landing system map, in a 1200 x 720
 * viewBox. The map reads like a transit diagram: stations sit on lines, the
 * request path runs left to right along the top, the event stream is a bar
 * beneath it, evaluation stations hang off that bar, and the evidence store
 * is a second bar at the bottom that the verdicts drain into.
 */
export const VIEW_W = 1200;
export const VIEW_H = 720;

/** Station marker radius. */
export const R = 9;

export interface NodeBox {
  kind: "station" | "bar";
  cx: number;
  cy: number;
  /** Width and height of the pointer target (stations) or the bar itself. */
  w: number;
  h: number;
  /** Lines of sub-label under a station’s name. Bars draw one line inside. */
  lines: string[];
  /** Where a station’s label sits, so connectors never run through text. */
  placement: "below" | "above" | "right";
}

function station(
  cx: number,
  cy: number,
  lines: string[],
  placement: NodeBox["placement"] = "below",
): NodeBox {
  return { kind: "station", cx, cy, w: 150, h: 96, lines, placement };
}

export const BOX: Record<NodeId, NodeBox> = {
  client: station(80, 100, ["a question", "about a filing"]),
  gateway: station(240, 100, ["the single", "front door"], "above"),
  input: station(400, 100, ["injection, PII,", "hazard checks"]),
  retrieval: station(560, 100, ["vector search,", "chunk checks"]),
  generation: station(720, 100, ["local model,", "bounded call"]),
  output: station(880, 100, ["schema, citations,", "faithfulness"]),
  response: station(1040, 100, ["an answer or", "a named block"]),
  stream: {
    kind: "bar",
    cx: 660,
    cy: 250,
    w: 920,
    h: 52,
    lines: ["Redpanda: responses, flash verdicts, frontier verdicts"],
    placement: "below",
  },
  flash: station(330, 380, ["gemini-3.6-flash,", "every answer"], "right"),
  sampler: station(560, 380, ["1 in 10 reviewed"]),
  frontier: station(780, 380, ["a second opinion,", "hosted Gemini"], "above"),
  calibration: station(1010, 380, ["measured against", "labeled data"]),
  store: {
    kind: "bar",
    cx: 660,
    cy: 540,
    w: 920,
    h: 52,
    lines: ["live views over the event stream"],
    placement: "below",
  },
  investigation: station(760, 650, ["one row per", "execution"]),
  mcp: station(1000, 650, ["five read tools"]),
};

export interface PlaneBand {
  plane: Plane;
  y: number;
  h: number;
  title: string;
  note: string;
}

export const BANDS: PlaneBand[] = [
  {
    plane: "request",
    y: 14,
    h: 178,
    title: "Request path",
    note: "the user waits for this",
  },
  {
    plane: "evaluation",
    y: 318,
    h: 174,
    title: "Evaluation plane",
    note: "runs after the answer is sent",
  },
  {
    plane: "evidence",
    y: 500,
    h: 206,
    title: "Evidence",
    note: "persisted and queryable",
  },
];

/** SVG path per edge, keyed "from>to". Each starts at the source marker’s
 * edge and ends a few units short of the target so the arrowhead lands on
 * the marker, never inside it. */
export const EDGE_PATH: Record<string, string> = {
  "client>gateway": "M91,100 H227",
  "gateway>input": "M251,100 H387",
  "input>retrieval": "M411,100 H547",
  "retrieval>generation": "M571,100 H707",
  "generation>output": "M731,100 H867",
  "output>response": "M891,100 H1027",
  "gateway>stream": "M240,111 V221",
  "stream>flash": "M330,276 V367",
  "stream>sampler": "M560,276 V367",
  "sampler>frontier": "M571,380 H767",
  "frontier>calibration": "M791,380 H997",
  "flash>store": "M330,391 V511",
  "frontier>store": "M780,391 V511",
  "stream>store": "M218,276 V511",
  "store>investigation": "M760,566 V637",
  "store>mcp": "M1000,566 V637",
};

export function edgeKey(from: NodeId, to: NodeId): string {
  return `${from}>${to}`;
}

export const EDGE_STYLE: Record<
  EdgeKind,
  { stroke: string; width: number; dash?: string }
> = {
  sync: { stroke: "var(--accent)", width: 3 },
  async: { stroke: "var(--signal)", width: 2, dash: "6 6" },
  measure: { stroke: "var(--text-secondary)", width: 1.5, dash: "2 5" },
};

export const PLANE_STROKE: Record<Plane, string> = {
  request: "var(--accent)",
  stream: "var(--text-secondary)",
  evaluation: "var(--signal)",
  evidence: "var(--text-secondary)",
};
