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
  NodeDetailStrip,
  type NodeDetail,
} from "@/components/arch/node-model";
import { NODES } from "@/lib/architecture-data";
import { LAYERS } from "@/lib/architecture-layers";

const P = "eval";

const EDGES: [string, string][] = [
  ["event", "flash"],
  ["event", "sampler"],
  ["flash", "flashVerdict"],
  ["sampler", "frontier"],
  ["frontier", "frontierVerdict"],
  ["flashVerdict", "store"],
  ["frontierVerdict", "store"],
  ["benchmark", "frontier"],
  ["frontier", "kappa"],
  ["kappa", "thresholds"],
];

const both = (id: "flash" | "sampler" | "frontier" | "store"): string =>
  `${NODES[id].summary} ${NODES[id].why}`;

const DETAILS: Record<string, NodeDetail> = {
  event: {
    title: "Response event",
    text: "The gateway publishes one event per request after the decision. The judges read it from the stream, and nobody waits for it.",
  },
  flash: { title: "Flash judge", text: both("flash") },
  flashVerdict: {
    title: "Flash verdict",
    text: "The three flash scores, written back to the event stream. A verdict can be partial when one metric times out, and the platform keeps that distinction.",
  },
  sampler: { title: "Deterministic sampler", text: both("sampler") },
  frontier: { title: "Frontier judge", text: both("frontier") },
  frontierVerdict: {
    title: "Frontier verdict",
    text: "The frontier judge’s score, its written reasoning and the chunks it cited, written back to the event stream.",
  },
  store: { title: "Evidence store", text: both("store") },
  benchmark: {
    title: "Labeled benchmark",
    text: "FinQA hallucination rows with known labels. The frontier judge scores them, and its agreement with the labels is the calibration.",
  },
  kappa: {
    title: "Cohen’s kappa",
    text: "The agreement between the frontier judge’s verdicts and the labels, corrected for chance.",
  },
  thresholds: {
    title: "Drift thresholds",
    text: "The state enters drift at 0.43 and recovers at 0.54. The two differ on purpose, so a reading cannot flip the state by crossing a single value.",
  },
};

/**
 * Diagram 2, the evaluation plane, drawn as a branching topology. One
 * response event forks: every answer goes to the flash judge, and the
 * deterministic sampler passes one in ten to the frontier judge. Both
 * verdicts merge into the evidence store. Calibration is a separate region
 * below, because it measures the frontier judge and belongs to no request.
 * Every connector here is asynchronous.
 */
export function EvaluationTopology() {
  return (
    <div>
      <DiagramScope edges={EDGES} details={DETAILS}>
        <div className="hidden lg:block">
          <svg
            viewBox="0 0 1200 600"
            role="img"
            aria-label="The evaluation plane. A response event forks to the flash judge, which scores every answer, and to a deterministic sampler that passes one in ten to the frontier judge. Both verdicts flow to the evidence store. Below, calibration is a separate loop: a labeled benchmark feeds the frontier judge, whose agreement with the labels is measured as Cohen’s kappa and read against drift thresholds."
            className="h-auto w-full"
          >
            <ArrowDefs prefix={P} />

            <Region
              x={262}
              y={30}
              w={700}
              h={310}
              label="Judges run after the response was sent"
              tone="evaluation"
            />
            <Region
              x={262}
              y={410}
              w={900}
              h={170}
              label="Calibration, separate from any request"
              tone="muted"
              labelAtEnd
            />

            <Box
              x={30}
              y={168}
              w={170}
              h={84}
              id="event"
              title="Response event"
              lines={["published by", "the gateway"]}
              tone="stream"
            />

            <Box
              x={292}
              y={64}
              w={210}
              h={92}
              id="flash"
              title="Flash judge"
              lines={["gemini-3.6-flash, hosted", "scores every answer"]}
              tone="evaluation"
            />
            <Box
              x={730}
              y={74}
              w={190}
              h={72}
              id="flashVerdict"
              title="Flash verdict"
              lines={["three metrics scored"]}
              tone="stream"
            />

            <Box
              x={292}
              y={228}
              w={210}
              h={92}
              id="sampler"
              title="Deterministic sampler"
              lines={["a hash of the trace id", "keeps about 1 in 10"]}
              tone="evaluation"
            />
            <Box
              x={548}
              y={228}
              w={176}
              h={92}
              id="frontier"
              title="Frontier judge"
              lines={["gemini-rubric, hosted", "a second opinion"]}
              tone="evaluation"
            />
            <Box
              x={760}
              y={238}
              w={180}
              h={72}
              id="frontierVerdict"
              title="Frontier verdict"
              lines={["score, reasoning,", "cited chunks"]}
              tone="stream"
            />

            <Box
              x={1010}
              y={150}
              w={160}
              h={100}
              id="store"
              title="Evidence store"
              lines={["RisingWave", "one row per execution"]}
              tone="evidence"
            />

            <Edge
              prefix={P}
              kind="async"
              from="event"
              to="flash"
              d="M200,200 C250,200 240,110 288,110"
            />
            <Edge
              prefix={P}
              kind="async"
              from="event"
              to="sampler"
              d="M200,220 C250,220 240,274 288,274"
            />
            <Edge
              prefix={P}
              kind="async"
              from="flash"
              to="flashVerdict"
              d="M502,110 H726"
            />
            <Edge
              prefix={P}
              kind="async"
              from="sampler"
              to="frontier"
              d="M502,274 H544"
            />
            <Edge
              prefix={P}
              kind="async"
              from="frontier"
              to="frontierVerdict"
              d="M724,274 H756"
            />
            <Edge
              prefix={P}
              kind="async"
              from="flashVerdict"
              to="store"
              d="M920,110 C985,110 960,185 1006,190"
            />
            <Edge
              prefix={P}
              kind="async"
              from="frontierVerdict"
              to="store"
              d="M940,274 C990,274 970,214 1006,210"
            />
            <Label x={232} y={142} anchor="end" edge={["event", "flash"]}>
              every answer
            </Label>
            <Label x={232} y={304} anchor="end" edge={["event", "sampler"]}>
              every event, then 1 in 10
            </Label>

            <Box
              x={292}
              y={452}
              w={190}
              h={92}
              id="benchmark"
              title="Labeled benchmark"
              lines={["FinQA hallucination", "rows with known labels"]}
              tone="muted"
              dashed
            />
            <Box
              x={690}
              y={452}
              w={180}
              h={92}
              id="kappa"
              title="Cohen’s kappa"
              lines={["agreement with", "the labels"]}
              tone="muted"
              dashed
            />
            <Box
              x={920}
              y={452}
              w={220}
              h={92}
              id="thresholds"
              title="Drift thresholds"
              lines={["enter drift at 0.43,", "recover at 0.54"]}
              tone="muted"
              dashed
            />

            <Edge
              prefix={P}
              kind="muted"
              from="benchmark"
              to="frontier"
              d="M387,452 C387,380 600,390 620,324"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="frontier"
              to="kappa"
              d="M680,324 C700,390 780,390 780,448"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="kappa"
              to="thresholds"
              d="M870,498 H916"
            />
            <Label
              x={376}
              y={436}
              anchor="end"
              edge={["benchmark", "frontier"]}
            >
              scores the labeled rows
            </Label>
            <Label x={793} y={394} anchor="start" edge={["frontier", "kappa"]}>
              measured by
            </Label>
          </svg>
          <NodeDetailStrip />
          <ArchLegend items={["async", "muted"]} />
        </div>
      </DiagramScope>
      <div className="lg:hidden">
        <LaneOutline lanes={LAYERS[1].outline} />
      </div>
    </div>
  );
}
