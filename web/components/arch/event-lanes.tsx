import {
  ArchLegend,
  ArrowDefs,
  Box,
  Edge,
  Label,
  LaneOutline,
} from "@/components/arch/svg-parts";
import { LAYERS } from "@/lib/architecture-layers";

const P = "events";

const TRACKS = [
  { name: "responses", y: 266 },
  { name: "flash verdicts", y: 286 },
  { name: "frontier verdicts", y: 306 },
];

/**
 * Diagram 3, the event infrastructure, drawn as lanes around a log. The
 * log is the center of the picture: Redpanda as a bar with its three
 * topics as tracks. Everything above it writes (the gateway publishes,
 * consumers read responses and write verdicts back). Everything below it
 * reads (RisingWave builds views from all three topics, then a chain
 * carries them to the browser). Only the calibration file bypasses it.
 */
export function EventLanes() {
  return (
    <div>
      <div className="hidden lg:block">
        <svg
          viewBox="0 0 1200 650"
          role="img"
          aria-label="The event infrastructure in two lanes around a log. In the write lane, the gateway publishes to Redpanda, and the flash and frontier consumers read responses and write verdicts back. In the read lane, RisingWave reads all three topics, the dashboard service queries it, gateway endpoints relay snapshots every three seconds, and the browser receives them over Server-Sent Events. A calibration file on disk bypasses the log."
          className="h-auto w-full"
        >
          <ArrowDefs prefix={P} />

          <rect
            x={8}
            y={10}
            width={1184}
            height={196}
            rx={16}
            fill="var(--background-elevated)"
            stroke="var(--border)"
          />
          <text
            x={1170}
            y={36}
            textAnchor="end"
            fontSize={12}
            className="fill-text-tertiary"
          >
            <tspan fontSize={13} fontWeight={600} fill="var(--signal)">
              Write lane
            </tspan>
            {"  "}events and verdicts go in
          </text>
          <rect
            x={8}
            y={384}
            width={1184}
            height={256}
            rx={16}
            fill="var(--background-elevated)"
            stroke="var(--border)"
          />
          <text
            x={1170}
            y={410}
            textAnchor="end"
            fontSize={12}
            className="fill-text-tertiary"
          >
            <tspan fontSize={13} fontWeight={600} className="fill-text-primary">
              Read lane
            </tspan>
            {"  "}views come out
          </text>

          <g className="group/node">
            <title>
              Redpanda, the log. Three topics: responses, flash verdicts,
              frontier verdicts.
            </title>
            <rect
              x={40}
              y={230}
              width={1120}
              height={112}
              rx={24}
              fill="var(--surface)"
              stroke="var(--text-secondary)"
              strokeOpacity={0.6}
              strokeWidth={1.5}
              className="transition-[stroke-opacity] group-hover/node:[stroke-opacity:1]"
            />
            <text
              x={64}
              y={254}
              fontSize={14.5}
              fontWeight={600}
              className="fill-text-primary"
            >
              Redpanda, the log
            </text>
            {TRACKS.map((t) => (
              <g key={t.name}>
                <line
                  x1={236}
                  x2={1136}
                  y1={t.y}
                  y2={t.y}
                  stroke="var(--text-tertiary)"
                  strokeOpacity={0.6}
                  strokeWidth={2}
                />
                <text
                  x={64}
                  y={t.y + 4}
                  fontSize={12}
                  className="fill-text-secondary"
                >
                  {t.name}
                </text>
              </g>
            ))}
          </g>

          <Box
            x={64}
            y={64}
            w={180}
            h={78}
            title="Gateway"
            lines={["publishes, never waits"]}
            tone="request"
          />
          <Box
            x={380}
            y={64}
            w={220}
            h={78}
            title="Flash judge consumer"
            lines={["its own process"]}
            tone="evaluation"
          />
          <Box
            x={700}
            y={64}
            w={240}
            h={78}
            title="Frontier consumer"
            lines={["its own process"]}
            tone="evaluation"
          />

          <Edge prefix={P} kind="async" d="M154,142 V226" />
          <Label x={168} y={190} anchor="start">
            one event per request
          </Label>
          <Edge prefix={P} kind="async" d="M420,226 V146" />
          <Edge prefix={P} kind="async" d="M560,146 V226" />
          <Label x={412} y={190} anchor="end">
            reads responses
          </Label>
          <Label x={568} y={190} anchor="start">
            writes verdicts
          </Label>
          <Edge prefix={P} kind="async" d="M760,226 V146" />
          <Edge prefix={P} kind="async" d="M900,146 V226" />
          <Label x={752} y={190} anchor="end">
            reads responses
          </Label>
          <Label x={908} y={190} anchor="start">
            writes verdicts
          </Label>

          <Box
            x={64}
            y={450}
            w={200}
            h={90}
            title="RisingWave"
            lines={["reads all three topics", "eight materialized views"]}
            tone="evidence"
          />
          <Box
            x={354}
            y={450}
            w={200}
            h={90}
            title="Dashboard service"
            lines={["the only RisingWave", "client"]}
            tone="evidence"
          />
          <Box
            x={644}
            y={450}
            w={210}
            h={90}
            title="Gateway endpoints"
            lines={["traces and the stream", "polled every 3 seconds"]}
            tone="request"
          />
          <Box
            x={944}
            y={450}
            w={200}
            h={90}
            title="Browser"
            lines={["full-state snapshots", "over Server-Sent Events"]}
            tone="request"
          />

          <Edge prefix={P} kind="read" d="M164,346 V446" />
          <Label x={178} y={368} anchor="start">
            sources
          </Label>
          <Edge prefix={P} kind="read" d="M268,495 H350" />
          <Label x={309} y={486}>
            queries
          </Label>
          <Edge prefix={P} kind="read" d="M558,495 H640" />
          <Label x={599} y={486}>
            snapshot
          </Label>
          <Edge prefix={P} kind="read" d="M858,495 H940" />
          <Label x={899} y={486}>
            relays
          </Label>

          <Box
            x={334}
            y={590}
            w={240}
            h={40}
            title="Calibration file on disk"
            tone="muted"
            dashed
          />
          <Edge prefix={P} kind="muted" d="M454,588 V544" />
          <Label x={470} y={570} anchor="start">
            bypasses the log
          </Label>
        </svg>
        <ArchLegend items={["async", "read", "muted"]} />
      </div>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[2].outline} />
      </div>
    </div>
  );
}
