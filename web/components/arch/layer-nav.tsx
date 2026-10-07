"use client";

import { useEffect, useState } from "react";
import { LAYERS, type Layer } from "@/lib/architecture-layers";

const TONE: Record<Layer["id"], { dot: string; ring: string; lift: string }> = {
  "request-path": {
    dot: "bg-accent",
    ring: "text-accent",
    lift: "lift-accent",
  },
  "evaluation-plane": {
    dot: "bg-signal",
    ring: "text-signal",
    lift: "lift-signal",
  },
  "event-infrastructure": {
    dot: "bg-text-secondary",
    ring: "text-text-secondary",
    lift: "lift-accent",
  },
  "operational-interface": {
    dot: "bg-text-primary",
    ring: "text-text-primary",
    lift: "lift-accent",
  },
};

/** The four layers as a sequence of cards: where a request goes, how it is
 * judged, how the data travels and how an engineer or agent asks about it.
 * Each is a plain anchor, so the jump behavior is the browser's own. */
export function LayerCards() {
  return (
    <nav aria-label="Architecture layers" className="mt-10">
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {LAYERS.map((layer, i) => (
          <li key={layer.id} className="relative">
            <a
              href={`#${layer.id}`}
              className={`lift ${TONE[layer.id].lift} reveal-host border-line bg-background-elevated/70 flex h-full min-h-11 flex-col gap-2 rounded-xl border p-5`}
            >
              <span className="flex items-center justify-between">
                <span
                  className={`flex items-center gap-2 font-mono text-sm tabular-nums ${TONE[layer.id].ring}`}
                >
                  <span
                    aria-hidden="true"
                    className={`h-2 w-2 rounded-full ${TONE[layer.id].dot}`}
                  />
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  aria-hidden="true"
                  className="reveal-on-hover text-text-secondary text-base"
                >
                  ↓
                </span>
              </span>
              <span className="text-text-primary text-lg font-semibold tracking-tight text-balance">
                {layer.name}
              </span>
              <span className="text-text-secondary text-sm leading-snug">
                {layer.question}
              </span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Which layer section is under the top of the viewport. */
function useActiveLayer(): Layer["id"] | null {
  const [active, setActive] = useState<Layer["id"] | null>(null);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id as Layer["id"]);
        }
      },
      { rootMargin: "-25% 0px -65% 0px" },
    );
    for (const layer of LAYERS) {
      const el = document.getElementById(layer.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
  return active;
}

/** A slim bar that sticks under the global navigation and follows the page,
 * so the reader always knows which layer is on screen and can jump to
 * another. The anchors are the same ones the cards use. */
export function LayerRail() {
  const active = useActiveLayer();
  return (
    <nav
      aria-label="Jump to a layer"
      className="border-border bg-background/80 sticky top-[var(--nav-h)] z-30 border-b backdrop-blur-xl"
    >
      <ul className="thin-scroll mx-auto flex max-w-7xl gap-1 overflow-x-auto px-2 sm:px-6">
        {LAYERS.map((layer, i) => {
          const current = active === layer.id;
          return (
            <li key={layer.id} className="relative shrink-0">
              <a
                href={`#${layer.id}`}
                aria-current={current ? "location" : undefined}
                className={`flex min-h-11 items-center gap-2 px-3 text-sm transition-colors duration-[var(--dur-base)] ${current ? "text-text-primary font-medium" : "text-text-secondary hover:text-text-primary"}`}
              >
                <span
                  className={`font-mono text-xs tabular-nums ${current ? TONE[layer.id].ring : "text-text-tertiary"}`}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                {layer.name}
              </a>
              <span
                aria-hidden="true"
                className={`bg-accent absolute inset-x-3 bottom-0 h-0.5 origin-left rounded-full transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${current ? "scale-x-100" : "scale-x-0"}`}
              />
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
