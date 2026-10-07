import {
  ArchLegend,
  ArrowDefs,
  Box,
  Edge,
  Label,
  LaneOutline,
  Region,
} from "@/components/arch/svg-parts";
import { LAYERS } from "@/lib/architecture-layers";

const P = "iface";

const TOOLS = [
  "Failing traces",
  "Guardrail decisions",
  "Judge scores",
  "Injection search",
  "Drift report",
];

/**
 * Diagram 4, the operational interface, drawn as a hub with spokes. The
 * persisted evidence is the hub. Three screens for people read from it on
 * the left. On the right, the MCP server reads from it and fans out into
 * five read tools for an engineer or an agent. Nothing here writes back.
 * Red Team sits apart as a dashed chain that connects to nothing: it is
 * not built, and the diagram never draws it as working.
 */
export function InterfaceHub() {
  return (
    <div>
      <div className="hidden lg:block">
        <svg
          viewBox="0 0 1200 600"
          role="img"
          aria-label="The operational interface as a hub. Persisted evidence sits in the center. On the left, the Overview, Live Operations and Investigations screens read it for people. On the right, the MCP server reads it and exposes five read tools to an engineer or agent. At the bottom, Red Team is drawn dashed and unconnected, because it is not built."
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
            title="Overview"
            lines={["what needs attention"]}
            tone="evidence"
          />
          <Box
            x={50}
            y={168}
            w={230}
            h={64}
            title="Live Operations"
            lines={["telemetry and calibration"]}
            tone="evidence"
          />
          <Box
            x={50}
            y={256}
            w={230}
            h={64}
            title="Investigations"
            lines={["one row per execution"]}
            tone="evidence"
          />

          <g className="group/node">
            <title>
              Persisted evidence. Events and verdicts in RisingWave.
            </title>
            <circle
              cx={520}
              cy={200}
              r={96}
              fill="var(--surface)"
              stroke="var(--text-primary)"
              strokeOpacity={0.6}
              strokeWidth={2}
              className="transition-[stroke-opacity] group-hover/node:[stroke-opacity:1]"
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
          </g>

          <Edge prefix={P} kind="read" d="M424,200 C370,200 340,112 284,112" />
          <Edge prefix={P} kind="read" d="M424,200 H284" />
          <Edge prefix={P} kind="read" d="M424,200 C370,200 340,288 284,288" />

          <Box
            x={700}
            y={152}
            w={200}
            h={96}
            title="MCP server"
            lines={["OpenTelemetry", "instrumented"]}
            tone="evidence"
          />
          <Edge prefix={P} kind="read" d="M616,200 H696" />
          <Label x={656} y={190}>
            reads
          </Label>

          {TOOLS.map((tool, i) => {
            const y = 70 + i * 62;
            return (
              <g key={tool}>
                <Box
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
            title="Engineer or agent"
            lines={["asks why a trace failed"]}
            tone="muted"
          />
          <Edge prefix={P} kind="read" d="M800,250 V326" />

          <Region
            x={20}
            y={430}
            w={1160}
            h={150}
            label="Red Team: not built. Nothing in this row runs."
            tone="muted"
          />
          <Box
            x={50}
            y={480}
            w={250}
            h={72}
            title="Scenario registry"
            lines={["does not exist yet"]}
            tone="muted"
            dashed
          />
          <Box
            x={400}
            y={480}
            w={250}
            h={72}
            title="Scenario tool"
            lines={["an MCP tool, not registered"]}
            tone="muted"
            dashed
          />
          <Box
            x={750}
            y={480}
            w={250}
            h={72}
            title="Red Team route"
            lines={["shows this status, not a mock"]}
            tone="muted"
            dashed
          />
          <Edge prefix={P} kind="muted" d="M300,516 H396" />
          <Edge prefix={P} kind="muted" d="M650,516 H746" />
          <Label x={1090} y={522}>
            not connected
          </Label>
        </svg>
        <ArchLegend items={["read", "muted"]} />
      </div>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[3].outline} />
      </div>
    </div>
  );
}
