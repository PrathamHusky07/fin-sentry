"use client";

import { useId, useState, type CSSProperties, type PointerEvent } from "react";
import {
  ConceptGlyph,
  ConceptIcon,
  type ConceptId,
} from "@/components/concept-icons";
import { MarkShapes } from "@/components/mark";
import {
  COMPACT,
  CONCEPTS,
  CONCEPT_BY_ID,
  WIDE,
  conceptLinks,
  linkPath,
  placeConcepts,
  spokePath,
  type ConceptTone,
  type ConstellationLayout,
} from "@/lib/constellation";

const TONE_COLOR: Record<ConceptTone, string> = {
  accent: "var(--accent)",
  signal: "var(--signal)",
  neutral: "var(--text-primary)",
};

const TONE_TEXT: Record<ConceptTone, string> = {
  accent: "text-accent",
  signal: "text-signal",
  neutral: "text-text-primary",
};

// Labels carry a background-colored outline so a line passing behind one
// never cuts through its letters.
const LABEL_HALO: CSSProperties = {
  paintOrder: "stroke",
  stroke: "var(--background)",
  strokeWidth: 5,
  strokeLinejoin: "round",
};

type NodeState = "rest" | "active" | "related" | "dim";
type LinkState = "rest" | "lit" | "soft" | "dim";

function nodeState(id: ConceptId, active: ConceptId | null): NodeState {
  if (active === null) return "rest";
  if (id === active) return "active";
  return CONCEPT_BY_ID[active].related.includes(id) ? "related" : "dim";
}

function linkState(
  a: ConceptId,
  b: ConceptId,
  active: ConceptId | null,
): LinkState {
  if (active === null) return "rest";
  return a === active || b === active ? "lit" : "dim";
}

function spokeState(id: ConceptId, active: ConceptId | null): LinkState {
  if (active === null) return "rest";
  if (id === active) return "lit";
  return CONCEPT_BY_ID[active].related.includes(id) ? "soft" : "dim";
}

function order(i: number): CSSProperties {
  return { "--i": i } as CSSProperties;
}

interface Handlers {
  onHover: (id: ConceptId | null) => void;
  onFocus: (id: ConceptId | null) => void;
  onPin: (id: ConceptId) => void;
}

function Constellation({
  layout,
  active,
  focused,
  pinned,
  handlers,
  interactive,
}: {
  layout: ConstellationLayout;
  active: ConceptId | null;
  focused: ConceptId | null;
  pinned: ConceptId | null;
  handlers: Handlers;
  interactive: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const placed = placeConcepts(layout);
  const links = conceptLinks();
  const { cx, cy, rx, ry, core } = layout;
  const markSize = core * 0.9;

  return (
    <svg
      viewBox={`0 0 ${layout.w} ${layout.h}`}
      className="h-auto w-full"
      {...(interactive
        ? {
            role: "group",
            "aria-label":
              "Fin-Sentry system constellation. Seven concepts around the platform: guard, retrieve, generate, judge, calibrate, investigate and MCP.",
          }
        : { "aria-hidden": true })}
    >
      <defs>
        <radialGradient id={`${uid}-core`}>
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.28" />
          <stop offset="0.55" stopColor="var(--accent)" stopOpacity="0.08" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${uid}-disc`} cx="0.5" cy="0.35" r="0.8">
          <stop offset="0" stopColor="var(--surface-high)" />
          <stop offset="1" stopColor="var(--background-elevated)" />
        </radialGradient>
        <radialGradient id={`${uid}-node`} cx="0.5" cy="0.3" r="0.85">
          <stop offset="0" stopColor="var(--surface-high)" />
          <stop offset="1" stopColor="var(--background)" />
        </radialGradient>
      </defs>

      <g className="cn-ring" fill="none" stroke="var(--text-primary)">
        <ellipse
          cx={cx}
          cy={cy}
          rx={rx * 1.2}
          ry={ry * 1.22}
          strokeOpacity={0.07}
          strokeDasharray="2 7"
        />
        <ellipse cx={cx} cy={cy} rx={rx} ry={ry} strokeOpacity={0.1} />
        <ellipse
          cx={cx}
          cy={cy}
          rx={rx * 0.56}
          ry={ry * 0.56}
          strokeOpacity={0.07}
        />
        <path
          d={`M${cx - rx * 1.28},${cy} H${cx - core - 14} M${cx + core + 14},${cy} H${cx + rx * 1.28} M${cx},${cy - ry * 1.3} V${cy - core - 14} M${cx},${cy + core + 14} V${cy + ry * 1.3}`}
          strokeOpacity={0.06}
          strokeDasharray="1 6"
        />
      </g>

      {links.map(([a, b], i) => {
        const gap = Math.abs(
          CONCEPTS.findIndex((c) => c.id === a) -
            CONCEPTS.findIndex((c) => c.id === b),
        );
        const adjacent = gap === 1 || gap === CONCEPTS.length - 1;
        return (
          <path
            key={`${a}-${b}`}
            d={linkPath(layout, placed[a], placed[b], adjacent ? 0.34 : 0.22)}
            fill="none"
            stroke={TONE_COLOR[CONCEPT_BY_ID[a].tone]}
            strokeWidth={linkState(a, b, active) === "lit" ? 2 : 1.25}
            strokeLinecap="round"
            pathLength={1}
            data-state={linkState(a, b, active)}
            data-kind={adjacent ? "edge" : "chord"}
            className="cn-link cn-path"
            style={order(i + CONCEPTS.length)}
          />
        );
      })}

      {CONCEPTS.map((concept, i) => (
        <path
          key={`spoke-${concept.id}`}
          d={spokePath(layout, placed[concept.id])}
          fill="none"
          stroke={TONE_COLOR[concept.tone]}
          strokeWidth={spokeState(concept.id, active) === "lit" ? 2.25 : 1.25}
          strokeLinecap="round"
          pathLength={1}
          data-state={spokeState(concept.id, active)}
          className="cn-link cn-path"
          style={order(i)}
        />
      ))}

      <g className="cn-mark">
        <circle cx={cx} cy={cy} r={core * 2.1} fill={`url(#${uid}-core)`} />
        <circle
          cx={cx}
          cy={cy}
          r={core}
          fill={`url(#${uid}-disc)`}
          stroke="var(--text-primary)"
          strokeOpacity={0.16}
        />
        <circle
          cx={cx}
          cy={cy}
          r={core - 7}
          fill="none"
          stroke="var(--accent)"
          strokeOpacity={0.22}
          strokeDasharray="1 5"
        />
        <svg
          x={cx - markSize / 2}
          y={cy - markSize / 2 - (layout.labels ? 14 : 0)}
          width={markSize}
          height={markSize}
          viewBox="0 0 32 32"
          fill="none"
        >
          <MarkShapes />
        </svg>
        {layout.labels ? (
          <>
            <text
              x={cx}
              y={cy + core * 0.52}
              textAnchor="middle"
              fontSize={19}
              fontWeight={600}
              className="fill-text-primary"
            >
              Fin-Sentry
            </text>
            <text
              x={cx}
              y={cy + core * 0.52 + 17}
              textAnchor="middle"
              fontSize={12}
              className="fill-text-secondary"
            >
              Reliability for financial RAG
            </text>
          </>
        ) : null}
      </g>

      {CONCEPTS.map((concept, i) => {
        const { x, y, r } = placed[concept.id];
        const color = TONE_COLOR[concept.tone];
        const k = (r * 1.15) / 24;
        const state = nodeState(concept.id, active);
        return (
          <g key={concept.id} className="cn-node" style={order(i)}>
            <g
              className="cn-inner"
              data-state={state}
              data-keyboard={focused === concept.id}
              {...(interactive
                ? {
                    tabIndex: 0,
                    role: "button",
                    "aria-label": `${concept.label}. ${concept.role}.`,
                    "aria-pressed": pinned === concept.id,
                    onFocus: (e: React.FocusEvent<SVGGElement>) => {
                      if (e.currentTarget.matches(":focus-visible")) {
                        handlers.onFocus(concept.id);
                      }
                    },
                    onBlur: () => handlers.onFocus(null),
                    onKeyDown: (e: React.KeyboardEvent<SVGGElement>) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handlers.onPin(concept.id);
                      }
                    },
                  }
                : {})}
              onPointerEnter={(e: PointerEvent<SVGGElement>) => {
                if (e.pointerType === "mouse") handlers.onHover(concept.id);
              }}
              onPointerLeave={(e: PointerEvent<SVGGElement>) => {
                if (e.pointerType === "mouse") handlers.onHover(null);
              }}
              onClick={() => handlers.onPin(concept.id)}
            >
              <circle cx={x} cy={y} r={r + 16} fill="transparent" />
              <circle
                className="cn-halo"
                cx={x}
                cy={y}
                r={r + 14}
                fill={color}
                fillOpacity={0.16}
              />
              <circle
                className="cn-focus-ring"
                cx={x}
                cy={y}
                r={r + 7}
                fill="none"
                stroke="var(--accent)"
                strokeWidth={2}
              />
              <ellipse
                cx={x}
                cy={y + r + 3}
                rx={r * 0.8}
                ry={r * 0.16}
                fill="#000"
                fillOpacity={0.4}
              />
              <circle
                cx={x}
                cy={y}
                r={r}
                fill={`url(#${uid}-node)`}
                stroke={color}
                strokeOpacity={state === "rest" ? 0.55 : 0.95}
                strokeWidth={1.75}
              />
              <g
                transform={`translate(${x - 12 * k} ${y - 12 * k}) scale(${k})`}
                fill="none"
                stroke={color}
                strokeWidth={1.6 / k}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <ConceptGlyph id={concept.id} />
              </g>
              {layout.labels ? (
                <>
                  <text
                    x={x}
                    y={y + r + 25}
                    textAnchor="middle"
                    fontSize={16}
                    fontWeight={600}
                    className="fill-text-primary"
                    style={LABEL_HALO}
                  >
                    {concept.label}
                  </text>
                  <text
                    x={x}
                    y={y + r + 43}
                    textAnchor="middle"
                    fontSize={12.5}
                    className="fill-text-secondary"
                    style={LABEL_HALO}
                  >
                    {concept.role}
                  </text>
                  <text
                    className="cn-tag"
                    x={x}
                    y={y - r - 14}
                    textAnchor="middle"
                    fontSize={12}
                    fill={color}
                  >
                    {concept.plane}
                  </text>
                </>
              ) : null}
            </g>
          </g>
        );
      })}
    </svg>
  );
}

function Caption({ id }: { id: ConceptId | null }) {
  const concept = id ? CONCEPT_BY_ID[id] : null;
  return (
    <div
      aria-live="polite"
      className="border-line bg-background-elevated/70 relative mt-2 flex min-h-[9.5rem] flex-col justify-center gap-3 rounded-xl border px-5 py-4 backdrop-blur-sm sm:px-6 lg:min-h-[7.25rem] lg:flex-row lg:items-center lg:gap-8"
    >
      {concept ? (
        <>
          <div className="flex shrink-0 items-center gap-3 lg:w-60">
            <span
              className={`border-line-hover bg-surface flex h-11 w-11 items-center justify-center rounded-lg border ${TONE_TEXT[concept.tone]}`}
            >
              <ConceptIcon id={concept.id} className="h-6 w-6" />
            </span>
            <span>
              <span className="text-text-primary block text-lg font-semibold tracking-tight">
                {concept.label}
              </span>
              <span className={`block text-sm ${TONE_TEXT[concept.tone]}`}>
                {concept.plane}
              </span>
            </span>
          </div>
          <p className="text-text-secondary text-base leading-relaxed lg:flex-1">
            {concept.detail}
          </p>
          <p className="text-text-tertiary shrink-0 text-sm lg:w-44">
            Touches{" "}
            <span className="text-text-secondary">
              {concept.related
                .map((other) => CONCEPT_BY_ID[other].label)
                .join(", ")}
            </span>
          </p>
        </>
      ) : (
        <p className="text-text-secondary w-full text-base leading-relaxed">
          One reliability layer between a question and its evidence. Seven
          parts, each tied to the ones it works with. Point at a part, or tap
          one, to see what it does and what it touches.
        </p>
      )}
    </div>
  );
}

/**
 * The landing hero graphic: Fin-Sentry at the center and its seven concepts
 * around it. It is an identity picture and not a request diagram, so it
 * never draws a flow. Pointing at, focusing or tapping a concept lifts it,
 * lights the lines to what it touches and lets the rest recede. Everything
 * it says is a claim from the system model; there are no counts and no
 * traffic. The reveal is one-shot CSS and is removed by reduced motion.
 */
export function HeroConstellation() {
  const [hovered, setHovered] = useState<ConceptId | null>(null);
  const [focused, setFocused] = useState<ConceptId | null>(null);
  const [pinned, setPinned] = useState<ConceptId | null>(null);
  const active = hovered ?? focused ?? pinned;

  const handlers: Handlers = {
    onHover: setHovered,
    onFocus: setFocused,
    onPin: (id) => setPinned((current) => (current === id ? null : id)),
  };

  return (
    <div
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setPinned(null);
          setHovered(null);
        }
      }}
    >
      <div className="mx-auto hidden max-w-[1200px] lg:block">
        <Constellation
          layout={WIDE}
          active={active}
          focused={focused}
          pinned={pinned}
          handlers={handlers}
          interactive
        />
      </div>
      <div className="mx-auto max-w-[420px] lg:hidden">
        <Constellation
          layout={COMPACT}
          active={active}
          focused={focused}
          pinned={pinned}
          handlers={handlers}
          interactive={false}
        />
      </div>

      <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:hidden">
        {CONCEPTS.map((concept) => (
          <li key={concept.id}>
            <button
              type="button"
              aria-pressed={pinned === concept.id}
              onClick={() => handlers.onPin(concept.id)}
              className={`border-line flex min-h-11 w-full items-center gap-2.5 rounded-lg border px-3 text-left text-base transition-colors ${
                pinned === concept.id
                  ? "bg-surface-active text-text-primary border-line-active"
                  : "bg-background-elevated/70 text-text-secondary hover:bg-surface-hover"
              }`}
            >
              <span className={TONE_TEXT[concept.tone]}>
                <ConceptIcon id={concept.id} className="h-5 w-5" />
              </span>
              {concept.label}
            </button>
          </li>
        ))}
      </ul>

      <Caption id={active} />
    </div>
  );
}
