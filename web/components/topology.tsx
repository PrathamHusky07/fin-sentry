"use client";

import { useState } from "react";
import {
  EDGES,
  NODES,
  PLANE_LABEL,
  PLANE_NODES,
  PLANE_TIMING,
  relatedNodes,
  type NodeId,
  type Plane,
} from "@/lib/architecture-data";
import {
  BANDS,
  BOX,
  EDGE_PATH,
  EDGE_STYLE,
  PLANE_STROKE,
  VIEW_H,
  VIEW_W,
  edgeKey,
} from "@/lib/topology-layout";

const PLANE_ORDER: Plane[] = ["request", "stream", "evaluation", "evidence"];

const PLANE_TEXT: Record<Plane, string> = {
  request: "text-accent",
  stream: "text-text-secondary",
  evaluation: "text-signal",
  evidence: "text-text-secondary",
};

/**
 * The landing page’s systems topology. The request path is a solid line
 * across the top. Evaluation hangs off an event stream beneath it, drawn
 * dashed because it is asynchronous. Hovering or focusing a node brings its
 * direct connections forward and lets the rest recede. Below the lg
 * breakpoint the same data renders as a vertical, tap-to-expand list,
 * because a 1200 unit diagram scaled to a phone is unreadable.
 *
 * Motion is decorative: dashes drift along asynchronous edges to show
 * direction. Nothing here moves in response to real traffic, and there is
 * no live count anywhere in the diagram.
 */
export function Topology() {
  const [hovered, setHovered] = useState<NodeId | null>(null);
  const [focused, setFocused] = useState<NodeId | null>(null);
  const [lastActive, setLastActive] = useState<NodeId>("output");
  const [expanded, setExpanded] = useState<NodeId | null>(null);

  const active = hovered ?? focused;
  const related = active ? relatedNodes(active) : null;
  const detail = NODES[active ?? lastActive];

  function activate(id: NodeId | null, via: "hover" | "focus") {
    if (via === "hover") setHovered(id);
    else setFocused(id);
    if (id) setLastActive(id);
  }

  return (
    <div>
      <div
        role="group"
        aria-label="Fin-Sentry system topology. Select a stage to read what it does and why it exists."
        className="hidden lg:block"
      >
        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="h-auto w-full">
          <defs>
            {(["sync", "async", "measure"] as const).map((kind) => (
              <marker
                key={kind}
                id={`arrow-${kind}`}
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path
                  d="M1 1.5 L8.5 5 L1 8.5 Z"
                  fill={EDGE_STYLE[kind].stroke}
                />
              </marker>
            ))}
          </defs>

          {BANDS.map((band) => (
            <g key={band.plane}>
              <rect
                x={8}
                y={band.y}
                width={VIEW_W - 16}
                height={band.h}
                rx={16}
                className="fill-background-elevated"
                stroke="var(--border)"
              />
              <text
                x={28}
                y={band.y + 28}
                className="fill-text-tertiary font-mono"
                fontSize={11}
                letterSpacing={1.6}
              >
                {band.title}
              </text>
              <text
                x={28}
                y={band.y + 46}
                className="font-mono"
                fontSize={11}
                letterSpacing={1.2}
                fill={PLANE_STROKE[band.plane]}
                fillOpacity={0.85}
              >
                {band.timing}
              </text>
            </g>
          ))}

          {EDGES.map((edge) => {
            const style = EDGE_STYLE[edge.kind];
            const touches =
              active !== null && (edge.from === active || edge.to === active);
            const opacity = active === null ? 0.75 : touches ? 1 : 0.1;
            return (
              <path
                key={edgeKey(edge.from, edge.to)}
                d={EDGE_PATH[edgeKey(edge.from, edge.to)]}
                fill="none"
                stroke={style.stroke}
                strokeWidth={touches ? style.width + 0.75 : style.width}
                strokeDasharray={style.dash}
                strokeLinejoin="round"
                markerEnd={`url(#arrow-${edge.kind})`}
                opacity={opacity}
                className={edge.kind === "async" ? "edge-async" : undefined}
                style={{ transition: "opacity 200ms, stroke-width 200ms" }}
              />
            );
          })}

          <text
            x={267}
            y={228}
            className="fill-text-secondary"
            fontSize={11.5}
            opacity={active === null || related?.has("gateway") ? 0.9 : 0.15}
          >
            publishes the event, never waits
          </text>
          <text
            x={890}
            y={462}
            textAnchor="middle"
            className="fill-text-secondary"
            fontSize={11}
            opacity={
              active === null || related?.has("calibration") ? 0.9 : 0.15
            }
          >
            measures
          </text>

          {(Object.keys(BOX) as NodeId[]).map((id) => {
            const box = BOX[id];
            const node = NODES[id];
            const isActive = active === id;
            const dimmed = related !== null && !related.has(id);
            const x = box.cx - box.w / 2;
            const y = box.cy - box.h / 2;
            const isBus = id === "stream";
            const stroke = PLANE_STROKE[node.plane];
            const twoLines = box.lines.length > 1;
            const labelY = isBus
              ? box.cy - 6
              : twoLines
                ? box.cy - 14
                : box.cy - 6;
            return (
              <g
                key={id}
                tabIndex={0}
                role="button"
                aria-label={`${node.label}. ${node.summary}`}
                aria-controls="topology-detail"
                onMouseEnter={() => activate(id, "hover")}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => activate(id, "focus")}
                onClick={() => activate(id, "focus")}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    activate(id, "focus");
                  }
                }}
                onBlur={() => setFocused(null)}
                opacity={dimmed ? 0.3 : 1}
                style={{ transition: "opacity 200ms", cursor: "pointer" }}
                className="outline-none"
              >
                <rect
                  x={x}
                  y={y}
                  width={box.w}
                  height={box.h}
                  rx={isBus ? 26 : 10}
                  className={isActive ? "fill-surface-high" : "fill-surface"}
                  stroke={stroke}
                  strokeOpacity={isActive ? 1 : 0.45}
                  strokeWidth={isActive ? 2 : 1}
                  strokeDasharray={id === "calibration" ? "4 4" : undefined}
                  style={{ transition: "stroke-opacity 200ms" }}
                />
                <text
                  x={box.cx}
                  y={labelY}
                  textAnchor="middle"
                  className="fill-text-primary"
                  fontSize={14}
                  fontWeight={600}
                >
                  {node.label}
                </text>
                {box.lines.map((line, i) => (
                  <text
                    key={line}
                    x={box.cx}
                    y={labelY + 20 + i * 15}
                    textAnchor="middle"
                    className="fill-text-secondary"
                    fontSize={11.5}
                  >
                    {line}
                  </text>
                ))}
              </g>
            );
          })}
        </svg>

        <div
          id="topology-detail"
          aria-live="polite"
          className="border-border-strong bg-background-elevated mt-4 grid min-h-44 gap-x-10 gap-y-4 rounded-xl border p-6 md:grid-cols-[14rem_1fr_1fr]"
        >
          <div>
            <p className={`eyebrow ${PLANE_TEXT[detail.plane]}`}>
              {PLANE_LABEL[detail.plane]} · {PLANE_TIMING[detail.plane]}
            </p>
            <p className="text-text-primary mt-2 text-xl font-semibold tracking-tight">
              {detail.label}
            </p>
            <p className="text-text-tertiary mt-2 font-mono text-xs break-words">
              {detail.source}
            </p>
          </div>
          <div>
            <p className="eyebrow">What it does</p>
            <p className="text-text-secondary mt-2 text-[15px] leading-relaxed">
              {detail.summary}
            </p>
          </div>
          <div>
            <p className="eyebrow">Why it exists</p>
            <p className="text-text-secondary mt-2 text-[15px] leading-relaxed">
              {detail.why}
            </p>
          </div>
        </div>

        <ul className="text-text-secondary mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <li className="flex items-center gap-2">
            <svg width="28" height="8" aria-hidden="true">
              <path d="M0 4H28" stroke="var(--accent)" strokeWidth="1.75" />
            </svg>
            Synchronous call
          </li>
          <li className="flex items-center gap-2">
            <svg width="28" height="8" aria-hidden="true">
              <path
                d="M0 4H28"
                stroke="var(--signal)"
                strokeWidth="1.5"
                strokeDasharray="5 6"
              />
            </svg>
            Asynchronous hand-off
          </li>
          <li className="flex items-center gap-2">
            <svg width="28" height="8" aria-hidden="true">
              <path
                d="M0 4H28"
                stroke="var(--text-secondary)"
                strokeWidth="1.25"
                strokeDasharray="2 5"
              />
            </svg>
            Measures, not a data path
          </li>
          <li className="text-text-tertiary">
            Moving dashes are decorative. No request or rate is shown here.
          </li>
        </ul>
      </div>

      <div className="lg:hidden">
        {PLANE_ORDER.map((plane) => (
          <section key={plane} className="relative pb-8 last:pb-0">
            <h3 className={`eyebrow ${PLANE_TEXT[plane]}`}>
              {PLANE_LABEL[plane]} · {PLANE_TIMING[plane]}
            </h3>
            <ol className="border-border-strong mt-3 ml-1 flex flex-col gap-1 border-l pl-4">
              {PLANE_NODES[plane].map((id) => {
                const node = NODES[id];
                const open = expanded === id;
                return (
                  <li key={id} className="relative">
                    <span
                      aria-hidden="true"
                      className="bg-background-elevated absolute top-5 -left-[1.3rem] h-2.5 w-2.5 rounded-full border"
                      style={{ borderColor: PLANE_STROKE[plane] }}
                    />
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => setExpanded(open ? null : id)}
                      className="hover:bg-surface flex min-h-12 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left"
                    >
                      <span>
                        <span className="text-text-primary block text-base font-semibold">
                          {node.label}
                        </span>
                        <span className="text-text-secondary block text-sm">
                          {node.sub}
                        </span>
                      </span>
                      <svg
                        viewBox="0 0 20 20"
                        className={`text-text-tertiary h-5 w-5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.75"
                        aria-hidden="true"
                      >
                        <path d="M5 8l5 5 5-5" />
                      </svg>
                    </button>
                    {open ? (
                      <div className="text-text-secondary mb-2 space-y-3 px-3 pb-3 text-base leading-relaxed">
                        <p>{node.summary}</p>
                        <p>
                          <span className="text-text-primary font-medium">
                            Why it exists.{" "}
                          </span>
                          {node.why}
                        </p>
                        <p className="text-text-tertiary font-mono text-xs break-words">
                          {node.source}
                        </p>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}
