import type { Metadata } from "next";
import { RouteStub } from "@/components/route-stub";

export const metadata: Metadata = {
  title: "Red Team — Fin-Sentry",
};

export default function RedTeamPage() {
  return (
    <RouteStub
      title="Red Team Console"
      description="A console to fire stored adversarial scenarios (direct and indirect prompt injection, jailbreak attempts, prompt leakage) at a registered endpoint and watch them evaluated like any other request."
      reason="No stored-scenario registry exists yet -- the MCP server's run_red_team_scenario tool was deliberately left unregistered on Day 7 for the same reason, and is deferred to Day 10. There is nothing real to fire yet, so nothing renders here but this notice."
      provenance="NOT_AVAILABLE"
    />
  );
}
