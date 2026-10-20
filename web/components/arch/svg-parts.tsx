"use client";

import type { ReactNode } from "react";
import {
  useDiagramModel,
  useEdgeState,
  useLabelVisible,
  useNodeHandlers,
  useNodeState,
} from "@/components/arch/node-model";
import { useHash } from "@/lib/use-hash";

export type Tone = "request" | "stream" | "evaluation" | "evidence" | "muted";

export const TONE_STROKE: Record<Tone, string> = {
  request: "var(--accent)",
  stream: "var(--text-secondary)",
  evaluation: "var(--signal)",
  evidence: "var(--text-primary)",
  muted: "var(--text-tertiary)",
};

/** Arrowhead markers shared by every diagram on the page. The ids are
 * prefixed so two diagrams on one page never collide. */
export function ArrowDefs({ prefix }: { prefix: string }) {
  const kinds: [string, string][] = [
    ["signal", "var(--signal)"],
    ["accent", "var(--accent)"],
    ["muted", "var(--text-tertiary)"],
    ["light", "var(--text-secondary)"],
  ];
  return (
    <defs>
      {kinds.map(([id, color]) => (
        <marker
          key={id}
          id={`${prefix}-${id}`}
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M1 1.5 L8.5 5 L1 8.5 Z" fill={color} />
        </marker>
      ))}
    </defs>
  );
}

/** A node. It joins the diagram's interaction model when it has an `id`:
 * the box brightens on hover, focus or selection, and `lines` are the
 * plain-language sub-labels under the title. */
export function Box({
  id,
  x,
  y,
  w,
  h,
  title,
  lines = [],
  tone,
  dashed = false,
}: {
  id?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  lines?: string[];
  tone: Tone;
  dashed?: boolean;
}) {
  const stroke = TONE_STROKE[tone];
  const top = y + (h - (22 + lines.length * 16)) / 2 + 15;
  const label = [title, ...lines].join(". ");
  const state = useNodeState(id);
  const handlers = useNodeHandlers(id, label);
  return (
    <g
      {...handlers}
      data-state={state}
      className={id ? "arch-node" : undefined}
    >
      <title>{label}</title>
      <rect
        className="arch-halo"
        x={x - 7}
        y={y - 7}
        width={w + 14}
        height={h + 14}
        rx={15}
        fill={stroke}
        fillOpacity={0.12}
        stroke={stroke}
        strokeOpacity={0.35}
      />
      <rect
        className="arch-ring"
        x={x - 4}
        y={y - 4}
        width={w + 8}
        height={h + 8}
        rx={13}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={2}
      />
      <rect
        className="arch-body"
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        fill="var(--surface)"
        stroke={stroke}
        strokeOpacity={0.55}
        strokeWidth={1.5}
        strokeDasharray={dashed ? "5 4" : undefined}
      />
      <text
        x={x + w / 2}
        y={top}
        textAnchor="middle"
        fontSize={14.5}
        fontWeight={600}
        className="fill-text-primary"
      >
        {title}
      </text>
      {lines.map((line, i) => (
        <text
          key={line}
          x={x + w / 2}
          y={top + 18 + i * 16}
          textAnchor="middle"
          fontSize={12}
          className="fill-text-secondary"
        >
          {line}
        </text>
      ))}
    </g>
  );
}

/** A grouped region with a label tucked into its top-left corner. */
export function Region({
  x,
  y,
  w,
  h,
  label,
  tone,
  dashed = true,
  labelAtEnd = false,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  tone: Tone;
  dashed?: boolean;
  labelAtEnd?: boolean;
}) {
  const stroke = TONE_STROKE[tone];
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={18}
        fill={`color-mix(in srgb, ${stroke} 4%, transparent)`}
        stroke={stroke}
        strokeOpacity={0.4}
        strokeDasharray={dashed ? "3 6" : undefined}
      />
      <text
        x={labelAtEnd ? x + w - 18 : x + 18}
        y={y + 24}
        textAnchor={labelAtEnd ? "end" : "start"}
        fontSize={12.5}
        fill={stroke}
      >
        {label}
      </text>
    </g>
  );
}

export type EdgeStyle = "sync" | "async" | "read" | "muted";

const EDGE: Record<
  EdgeStyle,
  { stroke: string; width: number; dash?: string; marker: string }
> = {
  sync: { stroke: "var(--accent)", width: 3, marker: "accent" },
  async: { stroke: "var(--signal)", width: 2, dash: "6 6", marker: "signal" },
  read: { stroke: "var(--text-secondary)", width: 1.75, marker: "light" },
  muted: {
    stroke: "var(--text-tertiary)",
    width: 1.5,
    dash: "3 5",
    marker: "muted",
  },
};

export function Edge({
  d,
  kind,
  prefix,
  from,
  to,
  arrow = true,
}: {
  d: string;
  kind: EdgeStyle;
  prefix: string;
  /** The node ids the edge joins, so the model can light it. */
  from?: string;
  to?: string;
  arrow?: boolean;
}) {
  const style = EDGE[kind];
  const state = useEdgeState(from, to, kind);
  return (
    <g data-state={state} className="arch-edge">
      <path
        className="arch-edge-halo"
        d={d}
        fill="none"
        stroke={style.stroke}
        strokeWidth={style.width + 7}
        strokeLinejoin="round"
      />
      <path
        d={d}
        fill="none"
        stroke={style.stroke}
        strokeWidth={state === "lit" ? style.width + 1 : style.width}
        strokeDasharray={style.dash}
        strokeLinejoin="round"
        markerEnd={arrow ? `url(#${prefix}-${style.marker})` : undefined}
      />
    </g>
  );
}

export function Label({
  x,
  y,
  children,
  anchor = "middle",
  edge,
}: {
  x: number;
  y: number;
  children: ReactNode;
  anchor?: "start" | "middle" | "end";
  /** The connection this label belongs to; it recedes when unrelated. */
  edge?: [string, string];
}) {
  const visible = useLabelVisible(edge);
  return (
    <text
      x={x}
      y={y}
      textAnchor={anchor}
      fontSize={12}
      className="fill-text-secondary topo-fade"
      opacity={visible ? 1 : 0.15}
    >
      {children}
    </text>
  );
}

/** The key that makes the arrows mean something. Pointing at or focusing an
 * entry lights every edge of that kind in the diagram above it. */
export function ArchLegend({
  items,
  captions,
}: {
  items: EdgeStyle[];
  /** Wording for a diagram whose arrows mean something other than the request path's. */
  captions?: Partial<Record<EdgeStyle, string>>;
}) {
  const model = useDiagramModel();
  const text: Record<EdgeStyle, string> = {
    sync: "Synchronous call, the user waits",
    async: "Asynchronous hand-off",
    read: "Read of persisted data",
    muted: "Not built or not connected",
    ...captions,
  };
  return (
    <ul className="mt-4 flex flex-wrap items-center gap-2">
      {items.map((kind) => (
        <li key={kind}>
          <button
            type="button"
            aria-pressed={model?.kind === kind}
            onPointerEnter={(e) => {
              if (e.pointerType === "mouse") model?.setKind(kind);
            }}
            onPointerLeave={(e) => {
              if (e.pointerType === "mouse") model?.setKind(null);
            }}
            onFocus={() => model?.setKind(kind)}
            onBlur={() => model?.setKind(null)}
            onClick={() => model?.setKind(model.kind === kind ? null : kind)}
            className={`border-line text-text-secondary hover:text-text-primary hover:bg-surface-hover flex min-h-11 items-center gap-2.5 rounded-lg border px-3.5 text-sm transition-colors ${model?.kind === kind ? "bg-surface-hover border-line-active text-text-primary" : "bg-background-elevated/60"}`}
          >
            <svg width="28" height="8" aria-hidden="true">
              <path
                d="M0 4H28"
                stroke={EDGE[kind].stroke}
                strokeWidth={EDGE[kind].width}
                strokeDasharray={EDGE[kind].dash}
              />
            </svg>
            {text[kind]}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The narrow-screen fallback for a diagram: the same story as an
 * ordered outline, one lane at a time. */
export function LaneOutline({
  lanes,
}: {
  lanes: {
    caption: string;
    steps: { label: string; sub: string; anchor?: string }[];
  }[];
}) {
  const hash = useHash();
  return (
    <div className="space-y-8">
      {lanes.map((lane) => (
        <section key={lane.caption}>
          <h3 className="text-text-secondary text-sm font-medium">
            {lane.caption}
          </h3>
          <ol className="border-border-strong mt-3 ml-1 border-l pl-5">
            {lane.steps.map((step) => {
              const targeted =
                step.anchor !== undefined && step.anchor === hash;
              return (
                <li
                  key={step.label}
                  id={step.anchor}
                  className="relative pb-5 last:pb-0"
                >
                  <span
                    aria-hidden="true"
                    className={`absolute top-1.5 -left-[1.62rem] h-3 w-3 rounded-full border-2 transition-colors duration-[var(--dur-base)] ${targeted ? "bg-accent border-accent" : "bg-background border-text-secondary"}`}
                  />
                  <p
                    className={`text-base font-semibold ${targeted ? "text-accent" : "text-text-primary"}`}
                  >
                    {step.label}
                  </p>
                  <p className="text-text-secondary text-base leading-snug">
                    {step.sub}
                  </p>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
