import type { Metadata } from "next";
import { RouteStub } from "@/components/route-stub";

export const metadata: Metadata = {
  title: "Live Operations — Fin-Sentry",
};

export default function OperationsPage() {
  return (
    <RouteStub
      title="Live Operations"
      description="Request throughput, latency percentiles, guardrail fire rate, and cost, updating from a real Server-Sent Events connection to the gateway."
      reason="Day 8 builds the SSE transport end to end. The charts that read it are Day 9 work, built once the real snapshot feed is proven in the browser."
    />
  );
}
