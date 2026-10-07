import type { ConceptId } from "@/components/concept-icons";

/**
 * Data and geometry for the landing constellation: Fin-Sentry at the center
 * and the seven concepts of the system around it. This is an identity
 * graphic, not a request diagram, so there are no arrows and no direction.
 * A line between two concepts means the two touch in the platform, and the
 * `detail` text is the claim, restated from the system model in
 * lib/architecture-data.ts (which was read from the backend source).
 */
export type ConceptTone = "accent" | "signal" | "neutral";

export interface Concept {
  id: ConceptId;
  label: string;
  /** Short qualifier drawn under the label on the wide layout. */
  role: string;
  /** Which part of the system the concept belongs to. */
  plane: string;
  tone: ConceptTone;
  /** The contextual explanation shown when the concept is active. */
  detail: string;
  /** Concepts it directly touches. Must be symmetric. */
  related: ConceptId[];
  /** Primary concepts are drawn larger, for spatial hierarchy. */
  primary: boolean;
}

export const CONCEPTS: Concept[] = [
  {
    id: "guard",
    label: "Guard",
    role: "Rails on both sides",
    plane: "Request path",
    tone: "accent",
    detail:
      "Input rails check the question before retrieval. Output rails check the answer before it is sent. A rail that errors blocks the request instead of waving it through.",
    related: ["retrieve", "generate", "investigate"],
    primary: true,
  },
  {
    id: "retrieve",
    label: "Retrieve",
    role: "Closest chunks, checked",
    plane: "Request path",
    tone: "accent",
    detail:
      "The closest filing chunks come from pgvector. Each chunk is checked for source trust, injection and PII before it can reach the prompt.",
    related: ["guard", "generate"],
    primary: false,
  },
  {
    id: "generate",
    label: "Generate",
    role: "One bounded call",
    plane: "Request path",
    tone: "accent",
    detail:
      "A local model answers in JSON mode under a time budget and a circuit breaker, so a slow model cannot hold the gateway open.",
    related: ["guard", "retrieve", "judge"],
    primary: false,
  },
  {
    id: "judge",
    label: "Judge",
    role: "A second opinion",
    plane: "Evaluation plane",
    tone: "signal",
    detail:
      "A flash judge scores every delivered answer. A deterministic sampler sends about one in ten to a frontier judge for a second opinion.",
    related: ["generate", "calibrate", "investigate"],
    primary: true,
  },
  {
    id: "calibrate",
    label: "Calibrate",
    role: "Measures the judge",
    plane: "Evaluation plane",
    tone: "signal",
    detail:
      "The frontier judge is scored against a labeled financial hallucination benchmark with Cohen’s kappa. Today that is one manual reading, not a live monitor.",
    related: ["judge"],
    primary: false,
  },
  {
    id: "investigate",
    label: "Investigate",
    role: "Every execution kept",
    plane: "Evidence",
    tone: "neutral",
    detail:
      "Each persisted execution is one row with its rail outcome, retrieved chunks, scores and reasoning. Nothing is grouped or sampled away.",
    related: ["judge", "guard", "mcp"],
    primary: true,
  },
  {
    id: "mcp",
    label: "MCP",
    role: "Ask the platform why",
    plane: "Evidence",
    tone: "neutral",
    detail:
      "Five read tools expose failing traces, guardrail decisions, judge scores, injection search and the drift report to an engineer’s tooling.",
    related: ["investigate"],
    primary: false,
  },
];

export const CONCEPT_BY_ID: Record<ConceptId, Concept> = Object.fromEntries(
  CONCEPTS.map((c) => [c.id, c]),
) as Record<ConceptId, Concept>;

export interface ConstellationLayout {
  w: number;
  h: number;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  /** Angle of the first concept, degrees clockwise from the right. */
  startDeg: number;
  /** Node radii. */
  rPrimary: number;
  rNormal: number;
  /** Radius of the central identity disc. */
  core: number;
  labels: boolean;
  /** Per-concept nudge so the ring does not read as a perfect clock face. */
  drift: Partial<Record<ConceptId, [number, number]>>;
}

export const WIDE: ConstellationLayout = {
  w: 1200,
  h: 590,
  cx: 600,
  cy: 292,
  rx: 448,
  ry: 208,
  startDeg: 205,
  rPrimary: 34,
  rNormal: 27,
  core: 84,
  labels: true,
  drift: {
    retrieve: [0, 10],
    judge: [-12, 0],
    calibrate: [0, -8],
    investigate: [0, -14],
  },
};

export const COMPACT: ConstellationLayout = {
  w: 400,
  h: 400,
  cx: 200,
  cy: 200,
  rx: 142,
  ry: 150,
  startDeg: 205,
  rPrimary: 25,
  rNormal: 20,
  core: 46,
  labels: false,
  drift: {},
};

export interface PlacedConcept {
  x: number;
  y: number;
  r: number;
}

export function placeConcepts(
  layout: ConstellationLayout,
): Record<ConceptId, PlacedConcept> {
  const out = {} as Record<ConceptId, PlacedConcept>;
  CONCEPTS.forEach((concept, i) => {
    const theta =
      ((layout.startDeg + (360 / CONCEPTS.length) * i) * Math.PI) / 180;
    const [dx, dy] = layout.drift[concept.id] ?? [0, 0];
    out[concept.id] = {
      x: round(layout.cx + layout.rx * Math.cos(theta) + dx),
      y: round(layout.cy + layout.ry * Math.sin(theta) + dy),
      r: concept.primary ? layout.rPrimary : layout.rNormal,
    };
  });
  return out;
}

/** Each relation once, as an ordered pair. */
export function conceptLinks(): [ConceptId, ConceptId][] {
  const seen = new Set<string>();
  const pairs: [ConceptId, ConceptId][] = [];
  for (const concept of CONCEPTS) {
    for (const other of concept.related) {
      const key = [concept.id, other].sort().join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      pairs.push([concept.id, other]);
    }
  }
  return pairs;
}

/** A shallow curve between two nodes, bowed toward the center so the web
 * reads as a field and not a polygon. Starts and ends at the node edges. */
export function linkPath(
  layout: ConstellationLayout,
  from: PlacedConcept,
  to: PlacedConcept,
  pull: number,
): string {
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2;
  const cx = mx + (layout.cx - mx) * pull;
  const cy = my + (layout.cy - my) * pull;
  const a = edgePoint(from, cx, cy);
  const b = edgePoint(to, cx, cy);
  return `M${a.x},${a.y} Q${round(cx)},${round(cy)} ${b.x},${b.y}`;
}

/** The spoke from the identity disc out to a node. */
export function spokePath(
  layout: ConstellationLayout,
  to: PlacedConcept,
): string {
  const a = pointToward(layout.cx, layout.cy, to.x, to.y, layout.core);
  const b = edgePoint(to, layout.cx, layout.cy);
  return `M${a.x},${a.y} L${b.x},${b.y}`;
}

function edgePoint(node: PlacedConcept, tx: number, ty: number) {
  return pointToward(node.x, node.y, tx, ty, node.r + 5);
}

function pointToward(
  x: number,
  y: number,
  tx: number,
  ty: number,
  distance: number,
) {
  const dx = tx - x;
  const dy = ty - y;
  const len = Math.hypot(dx, dy) || 1;
  return {
    x: round(x + (dx / len) * distance),
    y: round(y + (dy / len) * distance),
  };
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}
