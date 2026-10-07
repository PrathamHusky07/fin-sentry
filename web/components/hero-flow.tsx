/**
 * The landing hero: one idea, drawn. A question travels the top lane while
 * the user waits, wrapped in protection on both sides of the model call.
 * One event leaves the gateway and the evaluation lane runs underneath it,
 * after the decision, where nobody waits. The two judges feed a single
 * investigation record, and calibration measures the frontier judge from
 * the side. Structural only: no counts, no traffic. The lanes draw in once
 * on load and the motion stops under prefers-reduced-motion.
 */

interface Station {
  id: string;
  x: number;
  y: number;
  name: string;
  lines: string[];
  tone: "request" | "evaluation" | "evidence";
  /** Label sits above the marker instead of below. */
  above?: boolean;
  /** Label sits to the right of the marker. */
  right?: boolean;
}

const STATIONS: Station[] = [
  {
    id: "client",
    x: 70,
    y: 100,
    name: "Question",
    lines: ["about a filing"],
    tone: "request",
  },
  {
    id: "gateway",
    x: 190,
    y: 100,
    name: "Gateway",
    lines: ["one front door"],
    tone: "request",
    above: true,
  },
  {
    id: "input",
    x: 330,
    y: 100,
    name: "Input rails",
    lines: ["injection, PII,", "hazard checks"],
    tone: "request",
  },
  {
    id: "retrieval",
    x: 470,
    y: 100,
    name: "Retrieval",
    lines: ["vector search,", "chunk checks"],
    tone: "request",
  },
  {
    id: "generation",
    x: 610,
    y: 100,
    name: "Generation",
    lines: ["one bounded call,", "local model"],
    tone: "request",
  },
  {
    id: "output",
    x: 750,
    y: 100,
    name: "Output rails",
    lines: ["schema, citations,", "faithfulness"],
    tone: "request",
  },
  {
    id: "answer",
    x: 960,
    y: 100,
    name: "Answer",
    lines: ["or a named block"],
    tone: "request",
  },
  {
    id: "event",
    x: 190,
    y: 300,
    name: "Event published",
    lines: ["after the decision"],
    tone: "evaluation",
  },
  {
    id: "flash",
    x: 470,
    y: 240,
    name: "Flash judge",
    lines: ["every answer scored"],
    tone: "evaluation",
  },
  {
    id: "sampler",
    x: 470,
    y: 360,
    name: "Deterministic sampler",
    lines: ["1 in 10 reviewed again"],
    tone: "evaluation",
  },
  {
    id: "frontier",
    x: 740,
    y: 360,
    name: "Frontier judge",
    lines: ["a second opinion"],
    tone: "evaluation",
    above: true,
  },
  {
    id: "investigation",
    x: 1010,
    y: 300,
    name: "Investigation",
    lines: ["every execution kept"],
    tone: "evidence",
  },
  {
    id: "calibration",
    x: 740,
    y: 440,
    name: "Calibration",
    lines: ["measured against", "labeled data"],
    tone: "evaluation",
    right: true,
  },
];

const TONE: Record<Station["tone"], string> = {
  request: "var(--accent)",
  evaluation: "var(--signal)",
  evidence: "var(--text-primary)",
};

function Marker({ station }: { station: Station }) {
  const color = TONE[station.tone];
  return (
    <circle
      cx={station.x}
      cy={station.y}
      r={9}
      fill="var(--background)"
      stroke={color}
      strokeWidth={3}
      className="origin-center transition-transform duration-200 [transform-box:fill-box] group-hover/station:scale-[1.45]"
    />
  );
}

function StationLabel({ station }: { station: Station }) {
  const anchor = station.right ? "start" : "middle";
  const x = station.right ? station.x + 22 : station.x;
  const nameY = station.above
    ? station.y - 36
    : station.right
      ? station.y - 2
      : station.y + 34;
  return (
    <>
      <text
        x={x}
        y={nameY}
        textAnchor={anchor}
        fontSize={15}
        fontWeight={600}
        className="fill-text-primary"
      >
        {station.name}
      </text>
      {station.lines.map((line, i) => (
        <text
          key={line}
          x={x}
          y={nameY + 18 + i * 16}
          textAnchor={anchor}
          fontSize={12.5}
          className="fill-text-secondary"
        >
          {line}
        </text>
      ))}
    </>
  );
}

function HeroDiagram() {
  return (
    <svg
      viewBox="0 0 1200 500"
      role="img"
      aria-label="Fin-Sentry in one picture. A question travels the request path through input rails, retrieval, generation and output rails to an answer, with protection on both sides of the model call. One event leaves the gateway. Below, the evaluation lane runs after the decision: a flash judge scores every answer, a deterministic sampler sends one in ten to a frontier judge, calibration measures the frontier judge, and both verdicts feed the investigation record."
      className="h-auto w-full"
    >
      <defs>
        <marker
          id="hero-arrow-sync"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M1 1.5 L8.5 5 L1 8.5 Z" fill="var(--accent)" />
        </marker>
        <marker
          id="hero-arrow-async"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M1 1.5 L8.5 5 L1 8.5 Z" fill="var(--signal)" />
        </marker>
      </defs>

      <text x={70} y={30} fontSize={13} fontWeight={600} fill="var(--accent)">
        The user waits for this
      </text>

      <rect
        x={262}
        y={42}
        width={560}
        height={146}
        rx={18}
        fill="color-mix(in srgb, var(--accent) 5%, transparent)"
        stroke="var(--accent)"
        strokeOpacity={0.45}
        strokeDasharray="3 6"
      />
      <text x={282} y={66} fontSize={12.5} className="fill-text-secondary">
        Protection on both sides of the model call
      </text>

      <path
        d="M81,100 H949"
        fill="none"
        stroke="var(--accent)"
        strokeWidth={3}
        markerEnd="url(#hero-arrow-sync)"
        pathLength={1}
        className="hero-draw"
      />

      <line
        x1={0}
        x2={1200}
        y1={208}
        y2={208}
        stroke="var(--border-strong)"
        strokeDasharray="2 6"
      />
      <text x={206} y={234} fontSize={13} fontWeight={600} fill="var(--signal)">
        Nobody waits for this
      </text>

      <g className="hero-fade">
        <path
          d="M190,111 V288"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <text
          x={176}
          y={176}
          textAnchor="end"
          fontSize={12.5}
          className="fill-text-secondary"
        >
          <tspan x={176}>published once,</tspan>
          <tspan x={176} dy={16}>
            never waited on
          </tspan>
        </text>
        <path
          d="M201,296 C320,296 340,240 458,240"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <path
          d="M201,304 C320,304 340,360 458,360"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <path
          d="M481,360 H728"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <path
          d="M481,240 C760,240 800,296 998,296"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <path
          d="M751,360 C880,360 900,304 998,304"
          fill="none"
          stroke="var(--signal)"
          strokeWidth={2}
          strokeDasharray="6 6"
          markerEnd="url(#hero-arrow-async)"
        />
        <path
          d="M740,371 V428"
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth={1.5}
          strokeDasharray="2 5"
        />
      </g>

      {STATIONS.map((station) => (
        <g key={station.id} className="group/station">
          <Marker station={station} />
          <StationLabel station={station} />
        </g>
      ))}
    </svg>
  );
}

function LaneList({
  title,
  tone,
  ids,
}: {
  title: string;
  tone: "text-accent" | "text-signal";
  ids: string[];
}) {
  return (
    <section>
      <h2 className={`text-sm font-semibold ${tone}`}>{title}</h2>
      <ol className="border-border-strong mt-3 ml-1 border-l pl-5">
        {ids.map((id) => {
          const s = STATIONS.find((station) => station.id === id)!;
          return (
            <li key={id} className="relative pb-5 last:pb-0">
              <span
                aria-hidden="true"
                className="bg-background absolute top-1.5 -left-[1.62rem] h-3 w-3 rounded-full border-2"
                style={{ borderColor: TONE[s.tone] }}
              />
              <p className="text-text-primary text-base font-semibold">
                {s.name}
              </p>
              <p className="text-text-secondary text-base">
                {s.lines.join(" ")}
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function HeroFlow() {
  return (
    <div>
      <div className="hidden lg:block">
        <HeroDiagram />
      </div>
      <div className="grid gap-8 sm:grid-cols-2 lg:hidden">
        <LaneList
          title="The user waits for this"
          tone="text-accent"
          ids={[
            "client",
            "gateway",
            "input",
            "retrieval",
            "generation",
            "output",
            "answer",
          ]}
        />
        <LaneList
          title="Nobody waits for this"
          tone="text-signal"
          ids={[
            "event",
            "flash",
            "sampler",
            "frontier",
            "calibration",
            "investigation",
          ]}
        />
      </div>
    </div>
  );
}
