import {
  EDGES,
  NODES,
  relatedNodes,
  type NodeId,
} from "@/lib/architecture-data";
import {
  BANDS,
  BOX,
  EDGE_PATH,
  EDGE_STYLE,
  PLANE_STROKE,
  R,
  VIEW_H,
  VIEW_W,
  edgeKey,
} from "@/lib/topology-layout";

const MEASURE_EDGE = EDGES.find((edge) => edge.kind === "measure")!;

interface Handlers {
  onHover: (id: NodeId | null) => void;
  onSelect: (id: NodeId) => void;
  onKeyboardFocus: (id: NodeId | null) => void;
}

function NodeShell({
  id,
  dimmed,
  handlers,
  children,
}: {
  id: NodeId;
  dimmed: boolean;
  handlers: Handlers;
  children: React.ReactNode;
}) {
  const node = NODES[id];
  return (
    <g
      tabIndex={0}
      role="button"
      aria-label={`${node.label}. ${node.summary}`}
      aria-controls="topology-detail"
      onMouseEnter={() => handlers.onHover(id)}
      onMouseLeave={() => handlers.onHover(null)}
      onFocus={(e) => {
        handlers.onSelect(id);
        if (e.currentTarget.matches(":focus-visible")) {
          handlers.onKeyboardFocus(id);
        }
      }}
      onBlur={() => handlers.onKeyboardFocus(null)}
      onClick={() => handlers.onSelect(id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handlers.onSelect(id);
        }
      }}
      className="topo-fade cursor-pointer outline-none"
      opacity={dimmed ? 0.28 : 1}
    >
      {children}
    </g>
  );
}

function Station({
  id,
  active,
  dimmed,
  keyboardFocused,
  handlers,
}: {
  id: NodeId;
  active: boolean;
  dimmed: boolean;
  keyboardFocused: boolean;
  handlers: Handlers;
}) {
  const box = BOX[id];
  const node = NODES[id];
  const stroke = PLANE_STROKE[node.plane];
  const { placement } = box;
  const anchor = placement === "right" ? "start" : "middle";
  const textX = placement === "right" ? box.cx + 24 : box.cx;
  const nameY =
    placement === "above"
      ? box.cy - 22 - box.lines.length * 16
      : placement === "right"
        ? box.cy - 2
        : box.cy + 34;
  const hitX = placement === "right" ? box.cx - 20 : box.cx - box.w / 2;
  const hitY = placement === "above" ? nameY - 24 : box.cy - 26;
  return (
    <NodeShell id={id} dimmed={dimmed} handlers={handlers}>
      <rect
        x={hitX}
        y={hitY}
        width={box.w}
        height={placement === "above" ? 24 + box.lines.length * 16 + 52 : box.h}
        rx={10}
        fill="transparent"
        stroke={keyboardFocused ? "var(--accent)" : "none"}
        strokeWidth={2}
      />
      <circle
        cx={box.cx}
        cy={box.cy}
        r={R + 18}
        fill={stroke}
        opacity={active ? 0.08 : 0}
        className="topo-fade"
      />
      <circle
        cx={box.cx}
        cy={box.cy}
        r={R + 8}
        fill={stroke}
        opacity={active ? 0.26 : 0}
        className="topo-fade"
      />
      <circle
        cx={box.cx}
        cy={box.cy}
        r={R}
        fill={active ? stroke : "var(--background)"}
        stroke={stroke}
        strokeWidth={3}
        className="topo-grow"
        style={{ transform: active ? "scale(1.45)" : "scale(1)" }}
      />
      <text
        x={textX}
        y={nameY}
        textAnchor={anchor}
        fontSize={15}
        fontWeight={600}
        className={active ? "fill-text-primary" : "fill-text-primary/85"}
      >
        {node.label}
      </text>
      {box.lines.map((line, i) => (
        <text
          key={line}
          x={textX}
          y={nameY + 18 + i * 16}
          textAnchor={anchor}
          fontSize={12}
          className={active ? "fill-text-primary" : "fill-text-secondary"}
        >
          {line}
        </text>
      ))}
    </NodeShell>
  );
}

function Bar({
  id,
  active,
  dimmed,
  keyboardFocused,
  handlers,
}: {
  id: NodeId;
  active: boolean;
  dimmed: boolean;
  keyboardFocused: boolean;
  handlers: Handlers;
}) {
  const box = BOX[id];
  const node = NODES[id];
  const stroke = PLANE_STROKE[node.plane];
  const grow = active ? 3 : 0;
  return (
    <NodeShell id={id} dimmed={dimmed} handlers={handlers}>
      <rect
        x={box.cx - box.w / 2 - grow}
        y={box.cy - box.h / 2 - grow}
        width={box.w + grow * 2}
        height={box.h + grow * 2}
        rx={(box.h + grow * 2) / 2}
        className={active ? "fill-surface-high" : "fill-surface"}
        stroke={keyboardFocused ? "var(--accent)" : stroke}
        strokeOpacity={active || keyboardFocused ? 1 : 0.5}
        strokeWidth={active || keyboardFocused ? 2.5 : 1.5}
        style={{
          transition: "fill 200ms, stroke-opacity 200ms, stroke-width 200ms",
        }}
      />
      <text
        x={box.cx}
        y={box.cy - 4}
        textAnchor="middle"
        fontSize={15}
        fontWeight={600}
        className="fill-text-primary"
      >
        {node.label}
      </text>
      <text
        x={box.cx}
        y={box.cy + 14}
        textAnchor="middle"
        fontSize={12}
        className={active ? "fill-text-primary" : "fill-text-secondary"}
      >
        {box.lines[0]}
      </text>
    </NodeShell>
  );
}

/**
 * The system map as one SVG. The active station grows and brightens, its
 * direct connections light up, and everything unrelated recedes. Dashes
 * mark asynchronous hand-offs and are static: nothing here moves with
 * traffic, and there is no live count anywhere on the map.
 */
export function TopologyMap({
  active,
  keyboardFocused,
  handlers,
}: {
  active: NodeId | null;
  keyboardFocused: NodeId | null;
  handlers: Handlers;
}) {
  const related = active ? relatedNodes(active) : null;
  const activePlane = active ? NODES[active].plane : null;
  const labelOpacity = (ids: NodeId[]) =>
    active === null || ids.some((id) => related?.has(id)) ? 0.95 : 0.15;

  return (
    <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="h-auto w-full">
      <defs>
        {(["sync", "async", "measure"] as const).map((kind) => (
          <marker
            key={kind}
            id={`arrow-${kind}`}
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M1 1.5 L8.5 5 L1 8.5 Z" fill={EDGE_STYLE[kind].stroke} />
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
            stroke={
              activePlane === band.plane
                ? PLANE_STROKE[band.plane]
                : "var(--border)"
            }
            strokeOpacity={activePlane === band.plane ? 0.5 : 1}
            style={{ transition: "stroke 280ms, stroke-opacity 280ms" }}
          />
          <rect
            x={8}
            y={band.y}
            width={VIEW_W - 16}
            height={band.h}
            rx={16}
            fill={PLANE_STROKE[band.plane]}
            opacity={activePlane === band.plane ? 0.045 : 0}
            className="topo-fade"
          />
          <text
            x={28}
            y={band.y + 28}
            fontSize={13}
            fontWeight={600}
            fill={PLANE_STROKE[band.plane]}
          >
            {band.title}
          </text>
          <text
            x={28}
            y={band.y + 46}
            fontSize={12}
            className="fill-text-tertiary"
          >
            {band.note}
          </text>
        </g>
      ))}

      {EDGES.map((edge) => {
        const style = EDGE_STYLE[edge.kind];
        const touches =
          active !== null && (edge.from === active || edge.to === active);
        return (
          <g key={edgeKey(edge.from, edge.to)}>
            <path
              d={EDGE_PATH[edgeKey(edge.from, edge.to)]}
              fill="none"
              stroke={style.stroke}
              strokeWidth={style.width + 7}
              strokeLinejoin="round"
              opacity={touches ? 0.13 : 0}
              className="topo-fade"
            />
            <path
              d={EDGE_PATH[edgeKey(edge.from, edge.to)]}
              fill="none"
              stroke={style.stroke}
              strokeWidth={touches ? style.width + 1.25 : style.width}
              strokeDasharray={style.dash}
              strokeLinejoin="round"
              markerEnd={`url(#arrow-${edge.kind})`}
              opacity={active === null ? 0.8 : touches ? 1 : 0.1}
              className="topo-fade"
            />
          </g>
        );
      })}

      <text
        x={256}
        y={208}
        fontSize={12}
        className="fill-text-secondary topo-fade"
        opacity={labelOpacity(["gateway", "stream"])}
      >
        publishes the event, never waits
      </text>
      <text
        x={894}
        y={366}
        textAnchor="middle"
        fontSize={12}
        className="fill-text-secondary topo-fade"
        opacity={labelOpacity([MEASURE_EDGE.from, MEASURE_EDGE.to])}
      >
        {MEASURE_EDGE.label}
      </text>
      <text
        x={0}
        y={0}
        transform="translate(206 428) rotate(-90)"
        textAnchor="middle"
        fontSize={12}
        className="fill-text-secondary topo-fade"
        opacity={labelOpacity(["stream", "store"])}
      >
        every event is stored too
      </text>

      {(Object.keys(BOX) as NodeId[]).map((id) => {
        const Shape = BOX[id].kind === "bar" ? Bar : Station;
        return (
          <Shape
            key={id}
            id={id}
            active={active === id}
            dimmed={related !== null && !related.has(id)}
            keyboardFocused={keyboardFocused === id}
            handlers={handlers}
          />
        );
      })}
    </svg>
  );
}
