import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CapabilityStrip } from "@/components/capability-strip";
import { EvalTelemetry } from "@/components/eval-telemetry";
import { GatewayProbeReadout } from "@/components/gateway-probe-readout";
import { StartIncident } from "@/components/incidents/start-incident";
import type { GatewayProbeSummary } from "@/lib/gateway-probe";

const text = (markup: string) =>
  markup.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("capability strip", () => {
  const markup = renderToStaticMarkup(<CapabilityStrip />);

  it("names the four things the platform covers", () => {
    for (const title of [
      "Quality signals",
      "Judge calibration",
      "Disagreement analysis",
      "Evidence-backed investigations",
    ]) {
      expect(markup).toContain(title);
    }
  });

  it("makes no claim about the state of any service", () => {
    const words = text(markup);
    expect(words).not.toMatch(
      /connected|reachable|monitoring|\blive\b|\bago\b|offline/i,
    );
    expect(markup).not.toContain("rounded-full bg-");
    expect(markup).not.toContain("pulse-live");
    expect(markup).not.toMatch(/\d{1,2}:\d{2}/);
  });

  it("describes disagreement analysis as something to inspect, not something present", () => {
    expect(text(markup)).toContain("Inspect where the two judge tiers differ");
    expect(text(markup)).toContain(
      "Whether any exist depends on the stored record",
    );
  });

  it("does not imply a new investigation can run without the backend", () => {
    expect(text(markup)).toContain("running a new one needs the backend");
  });
});

describe("evaluation telemetry when the stream has not answered", () => {
  it("replaces the cards with an unavailable state", () => {
    const markup = renderToStaticMarkup(
      <EvalTelemetry snapshot={null} connection="error" />,
    );
    expect(text(markup)).toContain("Evaluation telemetry is unavailable");
    expect(markup).not.toContain("Flash judge, faithfulness");
  });

  it("keeps the cards while the first snapshot is still on its way", () => {
    const markup = renderToStaticMarkup(
      <EvalTelemetry snapshot={null} connection="connecting" />,
    );
    expect(markup).toContain("Flash judge, faithfulness");
    expect(text(markup)).not.toContain("unavailable");
  });
});

const run = (target: string): GatewayProbeSummary => ({
  runs_recorded: 1,
  latest: {
    measured_at: "2026-10-22T22:28:42Z",
    target,
    samples: 30,
    median_ms: 0.26,
    p95_ms: 0.35,
    max_ms: 0.38,
  },
});

describe("gateway health route readout", () => {
  it("labels the figure as the health-route round trip and not as evaluation latency", () => {
    const words = text(
      renderToStaticMarkup(
        <GatewayProbeReadout
          probe={run("http://localhost:8000/health")}
          health={null}
          now={null}
        />,
      ),
    );
    expect(words).toContain("Health-route round trip, recorded probe");
    expect(words).toContain("The route runs no retrieval and no model");
    expect(words).toContain("not how long an evaluation or an answer takes");
    expect(words).toContain(
      "It is stored, so it stays here until the next run replaces it",
    );
    expect(words).not.toMatch(/evaluation latency is|RAG latency/i);
  });

  it("states the timed boundaries and only claims the same machine for a local target", () => {
    const local = text(
      renderToStaticMarkup(
        <GatewayProbeReadout
          probe={run("http://localhost:8000/health")}
          health={null}
          now={null}
        />,
      ),
    );
    expect(local).toContain(
      "from the probe sending a GET to the gateway health route",
    );
    expect(local).toContain("until it had read the whole response");
    expect(local).toContain("same machine as the gateway");
    const remote = text(
      renderToStaticMarkup(
        <GatewayProbeReadout
          probe={run("https://gateway.example.com/health")}
          health={null}
          now={null}
        />,
      ),
    );
    expect(remote).not.toContain("same machine");
    // The target address is never printed, so no internal host or port reaches the page.
    expect(local).not.toMatch(/localhost|:8000/);
  });

  it("shows nothing in place of a reading when the store did not answer", () => {
    const words = text(
      renderToStaticMarkup(
        <GatewayProbeReadout probe={null} health={null} now={null} />,
      ),
    );
    expect(words).toContain("did not answer");
    expect(words).not.toContain("ms median");
  });
});

describe("starting an investigation when the gateway did not answer", () => {
  const markup = renderToStaticMarkup(<StartIncident available={false} />);

  it("offers no form and no way to submit one", () => {
    expect(text(markup)).toContain("Starting an investigation is unavailable");
    expect(markup).not.toMatch(/<form|<button|<input|<details/);
  });
});
