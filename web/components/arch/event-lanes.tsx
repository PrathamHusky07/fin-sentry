import {
  ArchLegend,
  ArrowDefs,
  Box,
  Edge,
  Label,
  LaneOutline,
} from "@/components/arch/svg-parts";
import {
  DiagramScope,
  Node,
  NodeDetailStrip,
  type NodeDetail,
} from "@/components/arch/node-model";
import { NODES } from "@/lib/architecture-data";
import { LAYERS } from "@/lib/architecture-layers";

const P = "events";

const EDGES: [string, string][] = [
  ["gateway", "log"],
  ["log", "flashConsumer"],
  ["flashConsumer", "log"],
  ["log", "frontierConsumer"],
  ["frontierConsumer", "log"],
  ["log", "risingwave"],
  ["risingwave", "dashboard"],
  ["dashboard", "endpoints"],
  ["endpoints", "browser"],
  ["calibrationFile", "dashboard"],
];

const DETAILS: Record<string, NodeDetail> = {
  gateway: {
    title: "Gateway",
    text: "Publishes one event per request and does not wait for delivery, so delivery is at-most-once and an event can be lost.",
  },
  log: {
    title: "Redpanda, the log",
    text: `${NODES.stream.summary} ${NODES.stream.why}`,
  },
  flashConsumer: {
    title: "Flash judge consumer",
    text: "The flash judge runs as its own process. It reads responses from the log and writes its verdicts back to it, so a judge can restart or lag without touching the request path.",
  },
  frontierConsumer: {
    title: "Frontier consumer",
    text: "The frontier judge runs as its own process. It reads responses, reviews the sampled ones and writes its verdicts back to the log.",
  },
  risingwave: {
    title: "RisingWave",
    text: `${NODES.store.summary} ${NODES.store.why}`,
  },
  dashboard: {
    title: "Dashboard service",
    text: "The only RisingWave client. The gateway never connects to RisingWave: a poller asks this service for a snapshot every three seconds.",
  },
  endpoints: {
    title: "Gateway endpoints",
    text: "Traces and the stream, polled every 3 seconds. Each message is full current state, so a reconnect just waits for the next one.",
  },
  browser: {
    title: "Browser",
    text: "Receives full-state snapshots over Server-Sent Events. A snapshot is never a delta and never an event log.",
  },
  calibrationFile: {
    title: "Calibration file on disk",
    text: "The calibration reading is not in RisingWave. The dashboard service reads a JSON file from disk, which is why the page labels it with the time it was written.",
  },
};

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
      <DiagramScope edges={EDGES} details={DETAILS}>
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
              <tspan
                fontSize={13}
                fontWeight={600}
                className="fill-text-primary"
              >
                Read lane
              </tspan>
              {"  "}views come out
            </text>

            <Node
              id="log"
              label="Redpanda, the log. Three topics: responses, flash verdicts, frontier verdicts."
            >
              <title>
                Redpanda, the log. Three topics: responses, flash verdicts,
                frontier verdicts.
              </title>
              <rect
                className="arch-halo"
                x={32}
                y={222}
                width={1136}
                height={128}
                rx={30}
                fill="var(--text-secondary)"
                fillOpacity={0.1}
              />
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
                className="arch-body"
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
            </Node>

            <Box
              x={64}
              y={64}
              w={180}
              h={78}
              id="gateway"
              title="Gateway"
              lines={["publishes, never waits"]}
              tone="request"
            />
            <Box
              x={380}
              y={64}
              w={220}
              h={78}
              id="flashConsumer"
              title="Flash judge consumer"
              lines={["its own process"]}
              tone="evaluation"
            />
            <Box
              x={700}
              y={64}
              w={240}
              h={78}
              id="frontierConsumer"
              title="Frontier consumer"
              lines={["its own process"]}
              tone="evaluation"
            />

            <Edge
              prefix={P}
              kind="async"
              from="gateway"
              to="log"
              d="M154,142 V226"
            />
            <Label x={168} y={190} anchor="start" edge={["gateway", "log"]}>
              one event per request
            </Label>
            <Edge
              prefix={P}
              kind="async"
              from="log"
              to="flashConsumer"
              d="M420,226 V146"
            />
            <Edge
              prefix={P}
              kind="async"
              from="flashConsumer"
              to="log"
              d="M560,146 V226"
            />
            <Label x={412} y={190} anchor="end" edge={["log", "flashConsumer"]}>
              reads responses
            </Label>
            <Label
              x={568}
              y={190}
              anchor="start"
              edge={["flashConsumer", "log"]}
            >
              writes verdicts
            </Label>
            <Edge
              prefix={P}
              kind="async"
              from="log"
              to="frontierConsumer"
              d="M760,226 V146"
            />
            <Edge
              prefix={P}
              kind="async"
              from="frontierConsumer"
              to="log"
              d="M900,146 V226"
            />
            <Label
              x={752}
              y={190}
              anchor="end"
              edge={["log", "frontierConsumer"]}
            >
              reads responses
            </Label>
            <Label
              x={908}
              y={190}
              anchor="start"
              edge={["frontierConsumer", "log"]}
            >
              writes verdicts
            </Label>

            <Box
              x={64}
              y={450}
              w={200}
              h={90}
              id="risingwave"
              title="RisingWave"
              lines={["reads all three topics", "eight materialized views"]}
              tone="evidence"
            />
            <Box
              x={354}
              y={450}
              w={200}
              h={90}
              id="dashboard"
              title="Dashboard service"
              lines={["the only RisingWave", "client"]}
              tone="evidence"
            />
            <Box
              x={644}
              y={450}
              w={210}
              h={90}
              id="endpoints"
              title="Gateway endpoints"
              lines={["traces and the stream", "polled every 3 seconds"]}
              tone="request"
            />
            <Box
              x={944}
              y={450}
              w={200}
              h={90}
              id="browser"
              title="Browser"
              lines={["full-state snapshots", "over Server-Sent Events"]}
              tone="request"
            />

            <Edge
              prefix={P}
              kind="read"
              from="log"
              to="risingwave"
              d="M164,346 V446"
            />
            <Label x={178} y={368} anchor="start" edge={["log", "risingwave"]}>
              sources
            </Label>
            <Edge
              prefix={P}
              kind="read"
              from="risingwave"
              to="dashboard"
              d="M268,495 H350"
            />
            <Label x={309} y={486} edge={["risingwave", "dashboard"]}>
              queries
            </Label>
            <Edge
              prefix={P}
              kind="read"
              from="dashboard"
              to="endpoints"
              d="M558,495 H640"
            />
            <Label x={599} y={486} edge={["dashboard", "endpoints"]}>
              snapshot
            </Label>
            <Edge
              prefix={P}
              kind="read"
              from="endpoints"
              to="browser"
              d="M858,495 H940"
            />
            <Label x={899} y={486} edge={["endpoints", "browser"]}>
              relays
            </Label>

            <Box
              x={334}
              y={590}
              w={240}
              h={40}
              id="calibrationFile"
              title="Calibration file on disk"
              tone="muted"
              dashed
            />
            <Edge
              prefix={P}
              kind="muted"
              from="calibrationFile"
              to="dashboard"
              d="M454,588 V544"
            />
            <Label
              x={470}
              y={570}
              anchor="start"
              edge={["calibrationFile", "dashboard"]}
            >
              bypasses the log
            </Label>
          </svg>
          <NodeDetailStrip />
          <ArchLegend items={["async", "read", "muted"]} />
        </div>
      </DiagramScope>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[2].outline} />
      </div>
    </div>
  );
}
