"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

/**
 * The one node-interaction model shared by all four architecture diagrams.
 *
 * Pointing at a node, focusing it or selecting it makes it the active node:
 * it is illuminated, the edges that touch it light up, the nodes it connects
 * to stay bright and everything unrelated recedes. A detail strip under the
 * diagram says what the active node is and what it connects to. Click or
 * Enter pins a node; Escape clears. The legend can also light every edge of
 * one kind. Nothing here is data: the details are the page's own prose.
 */
export type EdgeKindName = "sync" | "async" | "read" | "muted";

export interface NodeDetail {
  title: string;
  text: string;
}

interface Model {
  active: string | null;
  pinned: string | null;
  related: Set<string> | null;
  kind: EdgeKindName | null;
  details: Record<string, NodeDetail>;
  hover: (id: string | null) => void;
  focus: (id: string | null) => void;
  pin: (id: string) => void;
  clear: () => void;
  setKind: (kind: EdgeKindName | null) => void;
}

const ModelContext = createContext<Model | null>(null);

export type NodeState = "rest" | "active" | "related" | "dim";

export function useDiagramModel(): Model | null {
  return useContext(ModelContext);
}

/** How a node should look right now. Outside a scope everything is at rest. */
export function useNodeState(id: string | undefined): NodeState {
  const model = useContext(ModelContext);
  if (!model || !id) return "rest";
  if (model.kind !== null) return "rest";
  if (model.active === null || model.related === null) return "rest";
  if (id === model.active) return "active";
  return model.related.has(id) ? "related" : "dim";
}

/** How an edge should look. `lit` touches the active node or matches the
 * legend kind; `dim` does not; `rest` is the idle diagram. */
export function useEdgeState(
  from: string | undefined,
  to: string | undefined,
  kind: EdgeKindName,
): "rest" | "lit" | "dim" {
  const model = useContext(ModelContext);
  if (!model) return "rest";
  if (model.kind !== null) return model.kind === kind ? "lit" : "dim";
  if (model.active === null) return "rest";
  if (!from || !to) return "dim";
  return from === model.active || to === model.active ? "lit" : "dim";
}

/** True when a label tied to the edge `from > to` should stay bright. */
export function useLabelVisible(edge: [string, string] | undefined): boolean {
  const model = useContext(ModelContext);
  if (!model || !edge) return true;
  if (model.kind !== null) return true;
  if (model.active === null) return true;
  return edge[0] === model.active || edge[1] === model.active;
}

export function DiagramScope({
  edges,
  details,
  children,
}: {
  /** Every connection in the diagram, as node id pairs. */
  edges: [string, string][];
  details: Record<string, NodeDetail>;
  children: ReactNode;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [kind, setKind] = useState<EdgeKindName | null>(null);
  const active = hovered ?? focused ?? pinned;

  const model = useMemo<Model>(() => {
    let related: Set<string> | null = null;
    if (active) {
      related = new Set([active]);
      for (const [a, b] of edges) {
        if (a === active) related.add(b);
        if (b === active) related.add(a);
      }
    }
    return {
      active,
      pinned,
      related,
      kind,
      details,
      hover: setHovered,
      focus: setFocused,
      pin: (id) => setPinned((p) => (p === id ? null : id)),
      clear: () => {
        setPinned(null);
        setHovered(null);
        setKind(null);
      },
      setKind,
    };
  }, [active, pinned, kind, edges, details]);

  return (
    <ModelContext.Provider value={model}>
      <div
        onKeyDown={(e: KeyboardEvent) => {
          if (e.key === "Escape") model.clear();
        }}
      >
        {children}
      </div>
    </ModelContext.Provider>
  );
}

/** Props that make an SVG group a node: pointer, focus and key handling. */
export function useNodeHandlers(id: string | undefined, label: string) {
  const model = useContext(ModelContext);
  if (!model || !id) return {};
  return {
    tabIndex: 0,
    role: "button",
    "aria-label": label,
    "aria-pressed": model.pinned === id,
    onPointerEnter: (e: React.PointerEvent) => {
      if (e.pointerType === "mouse") model.hover(id);
    },
    onPointerLeave: (e: React.PointerEvent) => {
      if (e.pointerType === "mouse") model.hover(null);
    },
    onFocus: (e: React.FocusEvent<Element>) => {
      if (e.currentTarget.matches(":focus-visible")) model.focus(id);
    },
    onBlur: () => model.focus(null),
    onClick: () => model.pin(id),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        model.pin(id);
      }
    },
  };
}

/** Pointer, focus and click handling for a node that is a real element
 * (a button), as opposed to an SVG group that needs role and tabIndex. */
export function useNodeEvents(id: string) {
  const model = useContext(ModelContext);
  if (!model) return {};
  return {
    "aria-pressed": model.pinned === id,
    onPointerEnter: (e: React.PointerEvent) => {
      if (e.pointerType === "mouse") model.hover(id);
    },
    onPointerLeave: (e: React.PointerEvent) => {
      if (e.pointerType === "mouse") model.hover(null);
    },
    onFocus: (e: React.FocusEvent<Element>) => {
      if (e.currentTarget.matches(":focus-visible")) model.focus(id);
    },
    onBlur: () => model.focus(null),
    onClick: () => model.pin(id),
  };
}

/** A custom-shaped node (a log, a hub) that joins the model. */
export function Node({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  const state = useNodeState(id);
  const handlers = useNodeHandlers(id, label);
  return (
    <g {...handlers} data-state={state} className="arch-node">
      {children}
    </g>
  );
}

/** The strip under a diagram: what the active node is, and what it touches. */
export function NodeDetailStrip({
  hint = "Point at a part, or select one, to see what it does and what it connects to.",
}: {
  hint?: string;
}) {
  const model = useContext(ModelContext);
  if (!model) return null;
  const detail = model.active ? model.details[model.active] : null;
  const touches = model.related
    ? [...model.related]
        .filter((id) => id !== model.active)
        .map((id) => model.details[id]?.title)
        .filter((t): t is string => Boolean(t))
    : [];
  return (
    <div
      aria-live="polite"
      className="border-line-hover bg-background-elevated/80 relative mt-4 min-h-[6.5rem] overflow-hidden rounded-xl border px-5 py-4"
    >
      <span
        aria-hidden="true"
        className="bg-accent absolute inset-y-0 left-0 w-0.5 origin-center transition-transform duration-[var(--dur-base)]"
        style={{ transform: detail ? "scaleY(1)" : "scaleY(0)" }}
      />
      {detail ? (
        <div key={model.active} className="swap-in">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <p className="text-text-primary text-base font-semibold">
              {detail.title}
            </p>
            {model.pinned ? (
              <button
                type="button"
                onClick={model.clear}
                className="text-accent hover:text-text-primary min-h-11 px-1 text-sm underline underline-offset-4"
              >
                Clear selection
              </button>
            ) : null}
          </div>
          <p className="text-text-secondary mt-1 max-w-4xl text-base leading-relaxed">
            {detail.text}
          </p>
          {touches.length > 0 ? (
            <p className="text-text-tertiary mt-2 text-sm">
              Connects to{" "}
              <span className="text-text-secondary">{touches.join(", ")}</span>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-text-tertiary text-base leading-relaxed">{hint}</p>
      )}
    </div>
  );
}
