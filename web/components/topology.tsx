"use client";

import { useState } from "react";
import { TopologyMap } from "@/components/topology-map";
import {
  NODES,
  PLANE_LABEL,
  PLANE_NODES,
  PLANE_TIMING,
  type NodeId,
  type Plane,
} from "@/lib/architecture-data";
import { PLANE_STROKE } from "@/lib/topology-layout";

const PLANE_ORDER: Plane[] = ["request", "stream", "evaluation", "evidence"];

const PLANE_TEXT: Record<Plane, string> = {
  request: "text-accent",
  stream: "text-text-secondary",
  evaluation: "text-signal",
  evidence: "text-text-secondary",
};

function Legend() {
  const items = [
    {
      label: "Synchronous call",
      path: <path d="M0 4H28" stroke="var(--accent)" strokeWidth="3" />,
    },
    {
      label: "Asynchronous hand-off",
      path: (
        <path
          d="M0 4H28"
          stroke="var(--signal)"
          strokeWidth="2"
          strokeDasharray="6 6"
        />
      ),
    },
    {
      label: "Measurement, not a data path",
      path: (
        <path
          d="M0 4H28"
          stroke="var(--text-secondary)"
          strokeWidth="1.5"
          strokeDasharray="2 5"
        />
      ),
    },
  ];
  return (
    <ul className="text-text-secondary mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-2">
          <svg width="28" height="8" aria-hidden="true">
            {item.path}
          </svg>
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * The landing page’s system map. Hovering or focusing a station brightens
 * it and its connections and lets the rest recede; the caption strip under
 * the map says what the station does and why it exists. Below the lg
 * breakpoint the same data renders as a vertical, tap-to-expand list,
 * because a 1200 unit diagram scaled to a phone is unreadable.
 */
export function Topology() {
  const [hovered, setHovered] = useState<NodeId | null>(null);
  const [selected, setSelected] = useState<NodeId>("frontier");
  const [keyboardFocused, setKeyboardFocused] = useState<NodeId | null>(null);
  const [expanded, setExpanded] = useState<NodeId | null>(null);

  // Dimming and growth follow hover or keyboard focus only. The caption
  // strip keeps the last selection so it is never empty.
  const active = hovered ?? keyboardFocused;
  const detail = NODES[hovered ?? selected];

  return (
    <div>
      <div
        role="group"
        aria-label="Fin-Sentry system map. Each station is a stage of the platform."
        className="hidden lg:block"
      >
        <TopologyMap
          active={active}
          keyboardFocused={keyboardFocused}
          handlers={{
            onHover: setHovered,
            onSelect: setSelected,
            onKeyboardFocus: setKeyboardFocused,
          }}
        />

        <div
          id="topology-detail"
          aria-live="polite"
          className="border-line-hover bg-background-elevated/80 relative mt-4 grid min-h-40 gap-x-10 gap-y-4 overflow-hidden rounded-xl border p-6 md:grid-cols-[14rem_1fr_1fr]"
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-0.5"
            style={{ background: PLANE_STROKE[detail.plane] }}
          />
          <div key={`${detail.id}-a`} className="swap-in">
            <p className={`text-sm ${PLANE_TEXT[detail.plane]}`}>
              {PLANE_LABEL[detail.plane]}, {PLANE_TIMING[detail.plane]}
            </p>
            <p className="text-text-primary mt-1.5 text-xl font-semibold tracking-tight">
              {detail.label}
            </p>
            <p className="text-text-tertiary mt-1 text-sm">{detail.sub}</p>
          </div>
          <div key={`${detail.id}-b`} className="swap-in">
            <p className="text-text-tertiary text-sm">What it does</p>
            <p className="text-text-secondary mt-1.5 text-[15px] leading-relaxed">
              {detail.summary}
            </p>
          </div>
          <div key={`${detail.id}-c`} className="swap-in">
            <p className="text-text-tertiary text-sm">Why it exists</p>
            <p className="text-text-secondary mt-1.5 text-[15px] leading-relaxed">
              {detail.why}
            </p>
          </div>
        </div>
        <Legend />
      </div>

      <div className="lg:hidden">
        {PLANE_ORDER.map((plane) => (
          <section key={plane} className="relative pb-8 last:pb-0">
            <h3 className={`text-sm font-semibold ${PLANE_TEXT[plane]}`}>
              {PLANE_LABEL[plane]}, {PLANE_TIMING[plane]}
            </h3>
            <ol className="border-border-strong mt-3 ml-1 flex flex-col gap-1 border-l pl-4">
              {PLANE_NODES[plane].map((id) => {
                const node = NODES[id];
                const open = expanded === id;
                return (
                  <li key={id} className="relative">
                    <span
                      aria-hidden="true"
                      className="bg-background-elevated absolute top-5 -left-[1.3rem] h-2.5 w-2.5 rounded-full border-2"
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
