import {
  ArchLegend,
  ArrowDefs,
  Box,
  Edge,
  Label,
  LaneOutline,
  Region,
} from "@/components/arch/svg-parts";
import {
  DiagramScope,
  Node,
  NodeDetailStrip,
  type NodeDetail,
} from "@/components/arch/node-model";
import { NODES } from "@/lib/architecture-data";
import { LAYERS } from "@/lib/architecture-layers";

const P = "iface";

const EDGES: [string, string][] = [
  ["evidence", "overview"],
  ["evidence", "live"],
  ["evidence", "investigations"],
  ["evidence", "mcp"],
  ["mcp", "tool-0"],
  ["mcp", "tool-1"],
  ["mcp", "tool-2"],
  ["mcp", "tool-3"],
  ["mcp", "tool-4"],
  ["mcp", "agent"],
  ["registry", "scenarioTool"],
  ["scenarioTool", "route"],
];

const TOOL_NAMES = [
  "Failing traces",
  "Guardrail decisions",
  "Judge scores",
  "Injection search",
  "Drift report",
];

const DETAILS: Record<string, NodeDetail> = {
  overview: {
    title: "Overview",
    text: "What needs attention right now, derived from the persisted trace list and the persisted calibration reading. It holds no live telemetry.",
  },
  live: {
    title: "Live Operations",
    text: "Telemetry: stream state, request and evaluation readouts, the activity chart and the calibration instrument.",
  },
  investigations: {
    title: "Investigations",
    text: `${NODES.investigation.summary} ${NODES.investigation.why}`,
  },
  evidence: {
    title: "Persisted evidence",
    text: "Events and verdicts in RisingWave. The screens and the MCP server both read what was recorded, and neither changes it.",
  },
  mcp: {
    title: "MCP server",
    text: `${NODES.mcp.summary} ${NODES.mcp.why}`,
  },
  agent: {
    title: "Engineer or agent",
    text: "Uses the read tools to ask why a trace failed, without learning the schema behind the evidence.",
  },
  registry: {
    title: "Scenario registry",
    text: "Ten versioned scenarios stored as data, each aimed at a defense that exists in the code. One of them is a known gap that is expected to be missed.",
  },
  scenarioTool: {
    title: "Scenario tool",
    text: "The MCP tool that would fire Red Team scenarios. It is deliberately not registered, so an agent cannot start a run yet.",
  },
  route: {
    title: "Red Team route",
    text: "Fires stored scenarios at the live defenses and shows every stored execution with the layer that acted and the evidence it left.",
  },
  ...Object.fromEntries(
    TOOL_NAMES.map((name, i) => [
      `tool-${i}`,
      {
        title: name,
        text: `One of the five read tools the MCP server registers. It reads the persisted evidence and changes nothing.`,
      },
    ]),
  ),
};

/**
 * Diagram 4, the operational interface, drawn as a hub with spokes. The
 * persisted evidence is the hub. Three screens for people read from it on
 * the left. On the right, the MCP server reads from it and fans out into
 * five read tools for an engineer or an agent. Nothing here writes back.
 * Red Team sits apart. Its registry and route run, so they are drawn solid.
 * The MCP tool that would start scenarios is not registered, so it stays
 * dashed and unconnected.
 */
export function InterfaceHub() {
  return (
    <div>
      <DiagramScope edges={EDGES} details={DETAILS}>
        <div className="hidden lg:block">
          <svg
            viewBox="0 0 1200 600"
            role="img"
            aria-label="The MCP and operational interface as a hub. Persisted evidence sits in the center. On the left, the Overview, Live Operations and Investigations screens read it for people. On the right, the MCP server reads it and exposes five read tools to an engineer or agent. At the bottom, the Red Team scenario registry feeds the Red Team route, which runs. The MCP tool that would start scenarios is drawn dashed, because it is not registered."
            className="h-auto w-full"
          >
            <ArrowDefs prefix={P} />

            <Region
              x={20}
              y={30}
              w={290}
              h={340}
              label="Screens for people"
              tone="evidence"
              dashed={false}
            />
            <Box
              x={50}
              y={80}
              w={230}
              h={64}
              id="overview"
              title="Overview"
              lines={["what needs attention"]}
              tone="evidence"
            />
            <Box
              x={50}
              y={168}
              w={230}
              h={64}
              id="live"
              title="Live Operations"
              lines={["telemetry and calibration"]}
              tone="evidence"
            />
            <Box
              x={50}
              y={256}
              w={230}
              h={64}
              id="investigations"
              title="Investigations"
              lines={["one row per execution"]}
              tone="evidence"
            />

            <Node
              id="evidence"
              label="Persisted evidence. Events and verdicts in RisingWave."
            >
              <title>
                Persisted evidence. Events and verdicts in RisingWave.
              </title>
              <circle
                className="arch-halo"
                cx={520}
                cy={200}
                r={108}
                fill="var(--text-primary)"
                fillOpacity={0.08}
              />
              <circle
                cx={520}
                cy={200}
                r={96}
                fill="var(--surface)"
                stroke="var(--text-primary)"
                strokeOpacity={0.6}
                strokeWidth={2}
                className="arch-body"
              />
              <text
                x={520}
                y={190}
                textAnchor="middle"
                fontSize={16}
                fontWeight={600}
                className="fill-text-primary"
              >
                Persisted
              </text>
              <text
                x={520}
                y={210}
                textAnchor="middle"
                fontSize={16}
                fontWeight={600}
                className="fill-text-primary"
              >
                evidence
              </text>
              <text
                x={520}
                y={234}
                textAnchor="middle"
                fontSize={12}
                className="fill-text-secondary"
              >
                events and verdicts
              </text>
            </Node>

            <Edge
              prefix={P}
              kind="read"
              from="evidence"
              to="overview"
              d="M424,200 C370,200 340,112 284,112"
            />
            <Edge
              prefix={P}
              kind="read"
              from="evidence"
              to="live"
              d="M424,200 H284"
            />
            <Edge
              prefix={P}
              kind="read"
              from="evidence"
              to="investigations"
              d="M424,200 C370,200 340,288 284,288"
            />

            <Box
              x={700}
              y={152}
              w={200}
              h={96}
              id="mcp"
              title="MCP server"
              lines={["OpenTelemetry", "instrumented"]}
              tone="evidence"
            />
            <Edge
              prefix={P}
              kind="read"
              from="evidence"
              to="mcp"
              d="M616,200 H696"
            />
            <Label x={656} y={190} edge={["evidence", "mcp"]}>
              reads
            </Label>

            {TOOL_NAMES.map((tool, i) => {
              const y = 70 + i * 62;
              return (
                <g key={tool}>
                  <Box
                    id={`tool-${i}`}
                    x={980}
                    y={y}
                    w={200}
                    h={44}
                    title={tool}
                    tone="evidence"
                  />
                  <Edge
                    prefix={P}
                    kind="read"
                    from="mcp"
                    to={`tool-${i}`}
                    d={`M900,200 C940,200 940,${y + 22} 976,${y + 22}`}
                  />
                </g>
              );
            })}
            <Label x={1080} y={56}>
              five read tools
            </Label>

            <Box
              x={700}
              y={330}
              w={200}
              h={64}
              id="agent"
              title="Engineer or agent"
              lines={["asks why a trace failed"]}
              tone="muted"
            />
            <Edge
              prefix={P}
              kind="read"
              from="mcp"
              to="agent"
              d="M800,250 V326"
            />

            <Region
              x={20}
              y={430}
              w={1160}
              h={150}
              label="Red Team: the registry and route run. The MCP tool is not registered."
              tone="evidence"
            />
            <Box
              x={50}
              y={480}
              w={250}
              h={72}
              id="registry"
              title="Scenario registry"
              lines={["ten stored scenarios"]}
              tone="evidence"
            />
            <Box
              x={400}
              y={480}
              w={250}
              h={72}
              id="route"
              title="Red Team route"
              lines={["runs scenarios, shows results"]}
              tone="evidence"
            />
            <Box
              x={750}
              y={480}
              w={250}
              h={72}
              id="scenarioTool"
              title="Scenario tool"
              lines={["an MCP tool, not registered"]}
              tone="muted"
              dashed
            />
            <Edge
              prefix={P}
              kind="read"
              from="registry"
              to="route"
              d="M300,516 H396"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="route"
              to="scenarioTool"
              d="M650,516 H746"
            />
            <Label x={1090} y={522}>
              tool not built
            </Label>
          </svg>
          <NodeDetailStrip />
          <ArchLegend items={["read", "muted"]} />
        </div>
      </DiagramScope>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[3].outline} />
      </div>
    </div>
  );
}
